"""Coverage completion for research IAF-prune / TPSL modules:

- quantflow/strategy/research/iaf_prune.py
- quantflow/strategy/research/iaf_prune_cpcv.py
- quantflow/strategy/research/tpsl.py
- quantflow/strategy/research/tpsl_gate_adapter.py
- quantflow/strategy/research/tpsl_validation_report.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.research.iaf_prune import PruneConfig, prune_correlated_factors
from quantflow.strategy.research import iaf_prune_cpcv as iafc
from quantflow.strategy.research.tpsl import (
    TPSLConfig,
    TradeRecord,
    summarize_trades,
)
from quantflow.strategy.research.tpsl_gate_adapter import (
    _exits_from_barriers,
    make_dual_ma_tpsl_signal_fn,
)
from quantflow.strategy.research.tpsl_validation_report import (
    build_tpsl_validation_report,
)


def _rng_frame(n: int = 80, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({c: rng.normal(size=n) for c in ("a", "b", "c")})


# ---------------------------------------------------------------------------
# iaf_prune
# ---------------------------------------------------------------------------


def test_prune_columns_fallback_to_numeric() -> None:
    """columns=[] -> fall back to all numeric columns."""
    df = _rng_frame(60)
    r = prune_correlated_factors(df, columns=[], config=PruneConfig(min_periods=30))
    assert r.kept or r.dropped
    assert set(r.kept + r.dropped) == {"a", "b", "c"}


def test_prune_no_usable_columns_raises() -> None:
    df = pd.DataFrame({"s": ["x", "y", "z"] * 20})
    with pytest.raises(ValueError, match="no factor columns"):
        prune_correlated_factors(df, columns=[])


def test_prune_unknown_method_raises() -> None:
    df = _rng_frame(60)
    with pytest.raises(ValueError, match="unknown correlation method"):
        prune_correlated_factors(df, columns=["a", "b"], config=PruneConfig(method="kendall"))


def test_prune_prefer_skips_absent_and_duplicate() -> None:
    """prefer names absent from cols / already ordered -> `if` False branch."""
    df = _rng_frame(60)
    r = prune_correlated_factors(
        df,
        columns=["a", "b"],
        config=PruneConfig(prefer=("zzz", "a", "a")),
    )
    assert r.kept[0] == "a"


def test_prune_nan_correlation_skips_pair() -> None:
    """Constant column -> NaN corr -> continue keeps both."""
    df = pd.DataFrame({"a": [1.0] * 60, "b": np.random.default_rng(1).normal(size=60)})
    r = prune_correlated_factors(df, columns=["a", "b"], config=PruneConfig(min_periods=30))
    assert r.dropped == []
    assert set(r.kept) == {"a", "b"}


def test_prune_column_absent_from_corr(monkeypatch) -> None:
    """Corr matrix missing a column -> col dropped via the guard branch."""
    real_corr = pd.DataFrame.corr

    def fake_corr(self, *args, **kwargs):
        out = real_corr(self, *args, **kwargs)
        return out.drop(columns=["b"], errors="ignore")

    monkeypatch.setattr(pd.DataFrame, "corr", fake_corr)
    df = _rng_frame(80)
    r = prune_correlated_factors(df, columns=["a", "b", "c"], config=PruneConfig(min_periods=30))
    assert "b" in r.dropped


def test_prune_high_corr_drops_later_column() -> None:
    df = pd.DataFrame({"a": list(range(60)), "b": list(range(60)), "c": np.random.default_rng(2).normal(size=60)})
    r = prune_correlated_factors(df, columns=["a", "b", "c"], config=PruneConfig(min_periods=30))
    assert "b" in r.dropped
    assert r.pairwise_dropped and r.pairwise_dropped[0]["dropped"] == "b"


# ---------------------------------------------------------------------------
# iaf_prune_cpcv
# ---------------------------------------------------------------------------


def _ohlcv_df(n: int = 800, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n)))
    return pd.DataFrame(
        {
            "close": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "open": close,
            "volume": rng.uniform(1, 10, n),
        }
    )


def test_compute_iaf_frame_real_engine() -> None:
    frame = iafc._compute_iaf_frame(_ohlcv_df(300))
    assert len(frame.columns) >= 1
    assert "cci_20" in frame.columns


def test_compute_iaf_frame_no_factors_raises(monkeypatch) -> None:
    from quantflow.indicators.engine import IndicatorEngine

    monkeypatch.setattr(
        IndicatorEngine, "batch_calculate", lambda self, df: pd.DataFrame({"x": [1, 2]})
    )
    with pytest.raises(ValueError, match="no IAF factor columns"):
        iafc._compute_iaf_frame(_ohlcv_df(50))


def test_research_signal_validation() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="lag must be >= 1"):
        iafc.research_signal_from_kept_factors(frame, ["a"], lag=0)
    with pytest.raises(ValueError, match="kept factors empty"):
        iafc.research_signal_from_kept_factors(frame, [])
    with pytest.raises(ValueError, match="not present"):
        iafc.research_signal_from_kept_factors(frame, ["nope"])


def test_run_iaf_prune_cpcv_real_pipeline() -> None:
    rep = iafc.run_iaf_prune_cpcv(_ohlcv_df(800), cpcv_groups=4, cpcv_test_groups=1)
    assert rep["promotion_eligible"] is False
    assert rep["hard_bind_entry"] is False
    assert "kept" in rep["prune"]
    assert rep["signal"]["lag"] == 1
    assert rep["research_go"] in {"GO_DISCUSS", "NO-GO"}


def test_run_iaf_prune_cpcv_requires_close() -> None:
    with pytest.raises(ValueError, match="close required"):
        iafc.run_iaf_prune_cpcv(None)
    with pytest.raises(ValueError, match="close required"):
        iafc.run_iaf_prune_cpcv(pd.DataFrame({"x": [1.0]}))


def test_run_iaf_prune_cpcv_reindex_alignment(monkeypatch) -> None:
    """Factor frame with a different index -> reindex branch (100-101)."""
    df = _ohlcv_df(400)
    fake = pd.DataFrame(
        {c: np.random.default_rng(5).normal(size=300) for c in iafc.IAF_FACTOR_NAMES},
        index=pd.RangeIndex(10, 310),
    )
    monkeypatch.setattr(iafc, "_compute_iaf_frame", lambda _df: fake)
    monkeypatch.setattr(
        iafc, "cpcv_backtest", lambda *a, **k: {"pbo": 0.2, "passed": True, "n_paths": 4}
    )
    rep = iafc.run_iaf_prune_cpcv(df, cpcv_groups=4, cpcv_test_groups=1)
    assert rep["cpcv"]["decision"] == "PASS"


# ---------------------------------------------------------------------------
# tpsl
# ---------------------------------------------------------------------------


def test_resolved_pcts_atr_branch() -> None:
    cfg = TPSLConfig(atr_sl_mult=1.0, take_profit_pct=0.05, min_rr=2.0)
    sl, tp = cfg.resolved_pcts(3.0, 100.0)
    assert sl == pytest.approx(0.03)
    assert tp == pytest.approx(0.06)  # max(0.06, 0.05)
    # take_profit_pct == 0 -> skip explicit-TP override
    cfg2 = TPSLConfig(atr_sl_mult=1.0, take_profit_pct=0.0, min_rr=2.0)
    sl2, tp2 = cfg2.resolved_pcts(3.0, 100.0)
    assert tp2 == pytest.approx(0.06)


def test_resolved_pcts_zero_stop_raises() -> None:
    with pytest.raises(ValueError, match="stop_loss_pct"):
        TPSLConfig(stop_loss_pct=0.0).resolved_pcts(None, 100.0)


def test_resolved_pcts_auto_lift_tp() -> None:
    cfg = TPSLConfig(stop_loss_pct=0.03, take_profit_pct=0.04, min_rr=2.0)
    sl, tp = cfg.resolved_pcts(None, 100.0)
    assert tp == pytest.approx(0.06)  # lifted to min_rr * sl


def _sim_close(values, entries, high=None, low=None, cfg=None):
    idx = pd.RangeIndex(len(values))
    return (
        pd.Series(values, index=idx),
        pd.Series(entries, index=idx, dtype=bool),
        high,
        low,
        cfg,
    )


def test_simulate_ambiguous_bar_stop_first() -> None:
    """Both SL and TP touched on one bar -> pessimistic stop (182-183)."""
    from quantflow.strategy.research.tpsl import simulate_long_flat_tpsl

    close = pd.Series([100.0, 100.0])
    entries = pd.Series([True, False], dtype=bool)
    high = pd.Series([100.0, 107.0])
    low = pd.Series([100.0, 96.0])
    _eq, trades, _stats, _meta = simulate_long_flat_tpsl(
        close, entries, high=high, low=low, cfg=TPSLConfig()
    )
    assert trades[0].reason == "sl"
    assert trades[0].exit_price == pytest.approx(100 * (1 + 0.002) * 0.97 * (1 - 0.002))


def test_simulate_time_exit() -> None:
    from quantflow.strategy.research.tpsl import simulate_long_flat_tpsl

    close = pd.Series([100.0, 100.0, 100.0, 100.0])
    entries = pd.Series([True, False, False, False], dtype=bool)
    _eq, trades, _stats, _meta = simulate_long_flat_tpsl(
        close, entries, cfg=TPSLConfig(max_holding_bars=2)
    )
    assert trades and trades[0].reason == "time"
    assert trades[0].exit_i == 2


def test_summarize_trades_zero_sl_trade() -> None:
    """TradeRecord with sl_pct == 0 -> realized_rr skip branch (241->240)."""
    trades = [
        TradeRecord(
            entry_i=0, exit_i=1, entry_price=100.0, exit_price=101.0,
            pnl_pct=0.01, reason="tp", sl_pct=0.0, tp_pct=0.05, rr_planned=0.0,
        )
    ]
    stats = summarize_trades(trades)
    assert stats.n_trades == 1
    assert stats.avg_rr_realized == 0.0
    # TradeStats.to_dict() line
    assert stats.to_dict()["n_trades"] == 1


def test_simulate_signal_off_exit() -> None:
    from quantflow.strategy.research.tpsl import simulate_long_flat_tpsl

    close = pd.Series([100.0, 100.0, 100.0, 100.0])
    entries = pd.Series([True, False, False, False], dtype=bool)
    signal_on = pd.Series([True, True, False, True], dtype=bool)
    _eq, trades, _stats, _meta = simulate_long_flat_tpsl(
        close, entries, signal_on=signal_on, cfg=TPSLConfig()
    )
    assert trades and trades[0].reason == "signal"
    assert trades[0].exit_i == 2


def test_simulate_eod_force_close() -> None:
    from quantflow.strategy.research.tpsl import simulate_long_flat_tpsl

    close = pd.Series([100.0, 100.0, 100.0])
    entries = pd.Series([True, False, False], dtype=bool)
    _eq, trades, _stats, _meta = simulate_long_flat_tpsl(
        close, entries, cfg=TPSLConfig()
    )
    assert trades and trades[0].reason == "eod"
    assert trades[0].exit_i == 2


# ---------------------------------------------------------------------------
# tpsl_gate_adapter
# ---------------------------------------------------------------------------


def test_exits_from_barriers_time_exit() -> None:
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0])
    entries = pd.Series([True, False, False, False, False], dtype=bool)
    exits = _exits_from_barriers(
        close, entries, stop_loss_pct=0.04, take_profit_pct=0.1, max_holding_bars=2
    )
    assert bool(exits.iloc[2])  # time exit at bar 2
    assert not bool(exits.iloc[1])


def test_signal_fn_requires_close() -> None:
    fn = make_dual_ma_tpsl_signal_fn(fast=4, slow=8)
    with pytest.raises(ValueError, match="must contain 'close'"):
        fn(pd.DataFrame({"open": [1.0]}))


def test_signal_fn_zero_sl_all_false() -> None:
    fn = make_dual_ma_tpsl_signal_fn(fast=4, slow=8)
    df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
    entries, exits = fn(df, stop_loss_pct=0.0)
    assert not entries.any() and not exits.any()


# ---------------------------------------------------------------------------
# tpsl_validation_report
# ---------------------------------------------------------------------------


def test_build_tpsl_validation_report_requires_data() -> None:
    with pytest.raises(ValueError, match="close column required"):
        build_tpsl_validation_report(None)
    with pytest.raises(ValueError, match="close column required"):
        build_tpsl_validation_report(pd.DataFrame({"x": [1.0]}))


def test_build_tpsl_validation_report_single_point_space() -> None:
    """Default single-point space -> fixed-config note (line 120)."""
    rng = np.random.default_rng(31)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 700))))
    df = pd.DataFrame({"close": close})
    rep = build_tpsl_validation_report(df, fast=8, slow=24, optimize_trials=1)
    assert rep["promotion_eligible"] is False
    assert any("fixed barrier config" in n for n in rep["notes"])
    assert rep["decision"] in {"PASS", "NO-GO", None}


def test_build_tpsl_validation_report_underreported() -> None:
    rng = np.random.default_rng(32)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 700))))
    df = pd.DataFrame({"close": close})
    rep = build_tpsl_validation_report(df, fast=8, slow=24, claimed_n_trials=1)
    assert rep["decision"] == "NO-GO"
    assert rep["reason"] == "underreported n_trials — refuse GO"


def test_build_tpsl_validation_report_skip_gate() -> None:
    rng = np.random.default_rng(33)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 700))))
    df = pd.DataFrame({"close": close})
    rep = build_tpsl_validation_report(df, fast=8, slow=24, run_gate=False)
    assert rep["decision"] is None
    assert any("gate skipped" in n for n in rep["notes"])
