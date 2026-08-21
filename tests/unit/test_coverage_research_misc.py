"""Coverage completion for research misc modules:

- contract_pin, universe_config, n_trials_budget, benchmark_excess
- day_deviation, spot_perp_sim, btc_overlay_profiles, backtest, optimizer
- elliott_wave_wfo_smoke, elliott_cost_grid_contract,
  elliott_paper_replay_contract
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.research import benchmark_excess as be
from quantflow.strategy.research import contract_pin as cp
from quantflow.strategy.research import day_deviation as dd
from quantflow.strategy.research import spot_perp_sim as sps
from quantflow.strategy.research import universe_config as uc
from quantflow.strategy.research.n_trials_budget import (
    TrialsAccount,
    TrialsBreakdown,
    account_n_trials,
    assert_honest_n_trials,
    grid_size,
)
from quantflow.strategy.templates.spot_perp_arb import SpotPerpArbStrategy

# ---------------------------------------------------------------------------
# contract_pin
# ---------------------------------------------------------------------------


def test_to_ms_epoch_variants() -> None:
    assert cp._to_ms(1_700_000_000, role="start") == 1_700_000_000_000  # seconds
    assert cp._to_ms(1_700_000_000_000, role="start") == 1_700_000_000_000  # ms
    assert cp._to_ms("1700000000", role="start") == 1_700_000_000_000  # digit str


def test_to_ms_invalid_raises() -> None:
    with pytest.raises(cp.ContractPinError, match="bool"):
        cp._to_ms(True, role="start")
    with pytest.raises(cp.ContractPinError, match="empty"):
        cp._to_ms("", role="start")
    with pytest.raises(cp.ContractPinError, match="end_ms"):
        cp.parse_window_ms("2024-02-01", "2024-01-01")


def test_fingerprint_ohlcv_empty() -> None:
    assert cp.fingerprint_ohlcv(None) == "empty"
    assert cp.fingerprint_ohlcv(pd.DataFrame()) == "empty"


def test_fingerprint_ohlcv_no_ohlcv_columns() -> None:
    df = pd.DataFrame({"foo": [1, 2, 3], "bar": [4.0, 5.0, 6.0]})
    fp = cp.fingerprint_ohlcv(df)
    assert len(fp) == 16 and fp.isalnum()


def test_fingerprint_universe_without_timestamp() -> None:
    """Frames without timestamp -> start_ms/end_ms stay None (101->105 arc)."""
    df = pd.DataFrame({"close": [1.0, 2.0]})
    block = cp.fingerprint_universe({"X": df})
    assert block["symbols"]["X"]["start_ms"] is None
    assert block["symbols"]["X"]["end_ms"] is None
    assert block["symbol_count"] == 1


def test_build_window_pin_requires_pin() -> None:
    with pytest.raises(cp.ContractPinError, match="require_pin"):
        cp.build_window_pin(start="", end="2024-01-01", frames={}, require_pin=True)


def test_warn_if_unpinned_with_pin() -> None:
    """Both start and end present -> early return (line 176)."""
    assert cp.warn_if_unpinned("2024-01-01", "2024-02-01", require_pin=True) is None


def test_warn_if_unpinned_missing() -> None:
    with pytest.warns(UserWarning, match="no explicit start/end pin"):
        cp.warn_if_unpinned(None, None)
    with pytest.raises(cp.ContractPinError, match="no explicit start/end pin"):
        cp.warn_if_unpinned("", None, require_pin=True)


def test_load_and_fingerprint_symbols_skips_empty() -> None:
    good = pd.DataFrame(
        {
            "timestamp": [1, 2],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [1.0, 2.0],
        }
    )
    bare = pd.DataFrame({"close": [3.0, 4.0]})

    class MockStore:
        def query(self, sym, start=None, end=None, timeframe=None):
            return {"none": None, "empty": pd.DataFrame(), "good": good, "bare": bare}[sym]

    frames, block = cp.load_and_fingerprint_symbols(
        MockStore(),
        ["none", "empty", "good", "bare"],
        start_ms=1,
        end_ms=10,
        timeframe="1h",
    )
    assert set(frames) == {"good", "bare"}
    assert block["symbol_count"] == 2


# ---------------------------------------------------------------------------
# universe_config
# ---------------------------------------------------------------------------


def test_load_universe_config_missing_defaults(tmp_path) -> None:
    cfg = uc.load_universe_config(tmp_path / "nope.yaml")
    assert cfg["_missing"] is True
    assert cfg["baseline_default"] == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_load_universe_config_not_mapping(tmp_path) -> None:
    f = tmp_path / "u.yaml"
    f.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not a mapping"):
        uc.load_universe_config(f)


def test_as_symbol_list_variants() -> None:
    assert uc._as_symbol_list(None) == []
    assert uc._as_symbol_list("A, B ,C") == ["A", "B", "C"]
    assert uc._as_symbol_list([{"symbol": "X"}, "Y", "", 3]) == ["X", "Y"]
    assert uc._as_symbol_list(123) == []


def test_candidate_symbols_watchlist_and_dedup() -> None:
    cfg = {"candidates": ["A", "A", "B"], "watchlist": ["C", "B"]}
    out = uc.candidate_symbols(cfg, include_watchlist=True)
    assert out == ["A", "B", "C"]
    assert uc.candidate_symbols({"candidates": []}) == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_load_admitted_corrupt(tmp_path) -> None:
    f = tmp_path / "admitted.json"
    f.write_text("{not json", encoding="utf-8")
    assert uc.load_admitted(f) is None


def test_admitted_symbols_no_sla_rows(tmp_path) -> None:
    """admitted file without sla list -> 168->177 arc."""
    (tmp_path / "data" / "paper_replay" / "universe").mkdir(parents=True)
    (tmp_path / "data" / "paper_replay" / "universe" / "admitted.json").write_text(
        json.dumps({"symbols": ["X"]}), encoding="utf-8"
    )
    out = uc.admitted_symbols(repo_root=tmp_path)
    # X not in baseline_default -> intersection empty -> baseline fallback
    assert out == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_admitted_symbols_sla_rows_none_pass(tmp_path) -> None:
    """sla rows present but none pass -> 174->177 + 178 branches."""
    (tmp_path / "data" / "paper_replay" / "universe").mkdir(parents=True)
    (tmp_path / "data" / "paper_replay" / "universe" / "admitted.json").write_text(
        json.dumps({"symbols": ["X"], "sla": [{"symbol": "Y", "sla_pass": True}]}),
        encoding="utf-8",
    )
    out = uc.admitted_symbols(repo_root=tmp_path, require_sla_file=False)
    assert out == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_admitted_symbols_sla_rows_no_passes(tmp_path) -> None:
    """sla rows exist but every row fails -> passed set empty (174->177)."""
    (tmp_path / "data" / "paper_replay" / "universe").mkdir(parents=True)
    (tmp_path / "data" / "paper_replay" / "universe" / "admitted.json").write_text(
        json.dumps({"symbols": ["X"], "sla": [{"symbol": "Y", "sla_pass": False}]}),
        encoding="utf-8",
    )
    out = uc.admitted_symbols(repo_root=tmp_path)
    # symbols stay ["X"]; X not in baseline_default -> baseline fallback
    assert out == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def test_admitted_symbols_sla_empty_require_sla_file(tmp_path) -> None:
    (tmp_path / "data" / "paper_replay" / "universe").mkdir(parents=True)
    (tmp_path / "data" / "paper_replay" / "universe" / "admitted.json").write_text(
        json.dumps({"symbols": [], "sla": []}), encoding="utf-8"
    )
    assert uc.admitted_symbols(repo_root=tmp_path, require_sla_file=True) == []


def test_admitted_symbols_missing_file_require_sla(tmp_path) -> None:
    assert uc.admitted_symbols(repo_root=tmp_path, require_sla_file=True) == []


def test_write_admitted_and_csv(tmp_path) -> None:
    out = uc.write_admitted({"symbols": ["A"]}, repo_root=tmp_path)
    assert out.is_file()
    csv = uc.baseline_symbols_csv(repo_root=tmp_path)
    assert isinstance(csv, str)


# ---------------------------------------------------------------------------
# n_trials_budget
# ---------------------------------------------------------------------------


def test_trials_account_to_dict() -> None:
    acc = TrialsAccount(3, {"barrier_grid": 3}, underreported=True, notes=["n"])
    assert acc.to_dict()["underreported"] is True


def test_assert_honest_claimed_above() -> None:
    acc = assert_honest_n_trials(10, {"barrier_grid": 2})
    assert acc.n_trials_accounted == 10
    assert any("exceeds breakdown sum" in n for n in acc.notes)


def test_assert_honest_claimed_equal() -> None:
    """claimed == accounted -> no notes, no flag (98->101 arc)."""
    acc = assert_honest_n_trials(2, {"barrier_grid": 2})
    assert acc.underreported is False
    assert acc.n_trials_accounted == 2
    assert acc.notes == []


def test_assert_honest_underreported() -> None:
    acc = assert_honest_n_trials(1, {"barrier_grid": 5})
    assert acc.underreported is True
    assert acc.n_trials_accounted == 5


def test_grid_size_empty_and_zero_axis() -> None:
    assert grid_size({}) == 0
    assert grid_size({"a": ()}) == 0
    assert grid_size({"a": (1, 2), "b": (3, 4)}) == 4


def test_account_n_trials_negative_raises() -> None:
    with pytest.raises(ValueError, match=">= 0"):
        account_n_trials({"barrier_grid": -1})
    assert account_n_trials(TrialsBreakdown()).n_trials_accounted == 1


# ---------------------------------------------------------------------------
# benchmark_excess
# ---------------------------------------------------------------------------


def test_equity_stats_list_input_and_zero_start() -> None:
    stats = be.equity_stats([1.0, 2.0, 4.0])
    assert stats["return_pct"] == pytest.approx(300.0)
    zero = be.equity_stats([0.0, 5.0])
    assert zero["return_pct"] == 0.0


def test_buy_hold_nonpositive_first() -> None:
    out = be.buy_hold_equity_from_close([0.0, 2.0])
    assert out.empty
    assert be.buy_hold_equity_from_close([]).empty


def test_excess_vs_benchmark_too_short() -> None:
    rep = be.excess_vs_benchmark([1.0], [1.0, 2.0])
    assert rep.n_bars == 1
    assert rep.beats_benchmark is False


def test_excess_vs_benchmark_single_active_return() -> None:
    """Two points -> m < 2 -> information_ratio 0.0 (line 130)."""
    rep = be.excess_vs_benchmark([1.0, 1.1], [1.0, 1.05])
    assert rep.n_bars == 2
    assert rep.information_ratio == 0.0


def test_excess_vs_benchmark_beats() -> None:
    rep = be.excess_vs_benchmark([1.0, 1.2, 1.4], [1.0, 1.1, 1.2])
    assert rep.beats_benchmark is True
    assert rep.excess_return_pct > 0


def test_gate_beats_benchmark_flag_combinations() -> None:
    rep = be.excess_vs_benchmark([1.0, 1.2, 1.4], [1.0, 1.1, 1.2])
    # both flags -> line 170
    g1 = be.gate_beats_benchmark(rep, max_dd_not_worse_than_benchmark=True)
    assert g1["decision"] == "PASS"
    # require_positive_excess=False -> elif skipped (171->173) -> line 169 else
    g2 = be.gate_beats_benchmark(
        rep, require_positive_excess=False, max_dd_not_worse_than_benchmark=True
    )
    assert g2["decision"] in {"PASS", "FAIL"}
    assert "max_dd_le_benchmark" in g2["checks"]
    # plain excess check (line 172)
    g3 = be.gate_beats_benchmark(rep)
    assert g3["checks"]["excess_return_gt_0"] is True


# ---------------------------------------------------------------------------
# day_deviation
# ---------------------------------------------------------------------------


def _base(**over) -> dict:
    d = {
        "gate_present": True,
        "meta_present": True,
        "decision": "GO",
        "baseline_id": "Baseline-0",
        "metrics": {},
        "window": {"start": "s", "end": "e", "data_fingerprint": "fp"},
        "path_note": "note",
    }
    d.update(over)
    return d


def test_load_json_corrupt(tmp_path) -> None:
    f = tmp_path / "bad.json"
    f.write_text("{corrupt", encoding="utf-8")
    assert dd._load_json(f) is None
    f2 = tmp_path / "list.json"
    f2.write_text("[1, 2]", encoding="utf-8")
    assert dd._load_json(f2) is None  # not a dict


def test_load_baseline_snapshot_relative_paths(tmp_path) -> None:
    (tmp_path / "g.json").write_text(
        json.dumps({"decision": "GO", "metrics": {"sharpe": 1}}), encoding="utf-8"
    )
    (tmp_path / "m.json").write_text(json.dumps({"start": "2024"}), encoding="utf-8")
    (tmp_path / "f.json").write_text(json.dumps({"metrics": {"return_pct": 5.0}}), encoding="utf-8")
    snap = dd.load_baseline_snapshot(
        repo_root=tmp_path, gate_path="g.json", meta_path="m.json", full_path="f.json"
    )
    assert snap["gate_present"] is True
    assert snap["metrics"]["full_return_pct"] == 5.0  # full.metrics fallback (line 79)


def test_evaluate_day_deviation_no_artifacts_required() -> None:
    rep = dd.evaluate_day_deviation(
        baseline=_base(), thresholds=dd.DeviationThresholds(require_artifacts=False)
    )
    assert rep["status"] == "ok"


def test_evaluate_day_deviation_base_metrics_missing() -> None:
    """base_ret/base_dd None -> 181->184 and 184->189 arcs."""
    rep = dd.evaluate_day_deviation(
        baseline=_base(),  # metrics empty
        day_metrics={"return_pct": 3.0, "max_drawdown_pct": 4.0},
    )
    assert rep["pnl_diagnostic"]["delta"]["return_pp"] is None
    assert rep["status"] == "ok"


def test_evaluate_day_deviation_within_band() -> None:
    """Deltas inside band -> 219->233 and 233->248 arcs."""
    rep = dd.evaluate_day_deviation(
        baseline=_base(metrics={"full_return_pct": 5.0, "full_max_dd_pct": 10.0}),
        day_metrics={"return_pct": 6.0, "max_drawdown_pct": 11.0},
    )
    pnl = rep["pnl_diagnostic"]
    assert pnl["breaches"]["return"] is False
    assert pnl["breaches"]["max_dd"] is False
    assert rep["status"] == "ok"


def test_format_alert_message_with_pnl() -> None:
    msg = dd.format_alert_message(
        {
            "status": "degraded",
            "baseline": {"decision": "GO"},
            "issues": ["baseline gate.json missing"],
            "pnl_diagnostic": {"comparable": False},
        }
    )
    assert "(Path A" in msg or "Path A" in msg


def test_as_float_invalid() -> None:
    assert dd._as_float(None) is None
    assert dd._as_float("abc") is None
    assert dd._as_float("1.5") == 1.5


# ---------------------------------------------------------------------------
# spot_perp_sim
# ---------------------------------------------------------------------------


def _pair_df(n: int = 60, funding_steps=None, oi_drop_at: int | None = None) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    base = 100.0 + np.linspace(0, 0.1, n)
    f = np.zeros(n, dtype=float)
    settle = set()
    for start, value in sorted((funding_steps or {}).items()):
        nexts = sorted(s for s in (funding_steps or {}) if s > start)
        end = nexts[0] if nexts else n
        f[start:end] = value
        settle.add(start)
    df = pd.DataFrame(
        {
            "spot_open": base,
            "spot_close": base,
            "perp_open": base,
            "perp_close": base,
            "funding_rate": f,
            "funding_settle": np.array([1 if i in settle else 0 for i in range(n)], dtype=int),
            "open_interest": 1000.0 + np.arange(n) * 10.0,
        },
        index=idx,
    )
    if oi_drop_at is not None:
        df.loc[df.index[oi_drop_at], "open_interest"] *= 0.90
    return df


def test_spot_perp_summary_string() -> None:
    df = _pair_df(funding_steps={0: 0.0, 30: -0.002, 40: 0.0}, oi_drop_at=27)
    res = sps.SpotPerpPairSimulator().run(df)
    assert "SpotPerpPair" in res.summary()
    assert "Funding:" in res.summary()


def test_spot_perp_missing_columns() -> None:
    with pytest.raises(ValueError, match="Missing columns"):
        sps.SpotPerpPairSimulator().run(pd.DataFrame({"spot_close": [1.0]}))


def test_spot_perp_close_open_position_at_end() -> None:
    """Position still open at the last bar -> mark-to-market close block."""
    df = _pair_df(n=60, funding_steps={0: 0.0, 30: -0.002, 59: -0.004}, oi_drop_at=55)
    res = sps.SpotPerpPairSimulator(fee_per_leg=0.0005).run(df)
    assert res.num_trades == 1
    assert res.funding_income != 0.0  # settlement accrued at last bar


def test_spot_perp_total_return_collapse(monkeypatch) -> None:
    """Fee >= 1 -> total_return <= -1 -> annual_return -1.0 (line 179)."""
    df = _pair_df(n=60, funding_steps={0: 0.0, 30: -0.002})

    def fake_signals(self, frame):
        entries = pd.Series(False, index=frame.index)
        entries.iloc[58] = True  # entry on the last bar -> entry+exit fees both apply
        exits = pd.Series(False, index=frame.index)
        return entries, exits

    monkeypatch.setattr(SpotPerpArbStrategy, "generate_signals", fake_signals)
    res = sps.SpotPerpPairSimulator(fee_per_leg=1.0).run(df)
    assert res.total_return <= -1.0
    assert res.annual_return == -1.0


def test_spot_perp_non_finite_total_return(monkeypatch) -> None:
    """+inf perp close while in position -> +inf total_return -> annual 0.0 (181)."""
    df = _pair_df(funding_steps={0: 0.0, 30: -0.002})
    df.loc[df.index[59], "perp_close"] = np.inf

    def fake_signals(self, frame):
        entries = pd.Series(False, index=frame.index)
        entries.iloc[55] = True
        exits = pd.Series(False, index=frame.index)
        return entries, exits

    monkeypatch.setattr(SpotPerpArbStrategy, "generate_signals", fake_signals)
    res = sps.SpotPerpPairSimulator(fee_per_leg=0.0).run(df)
    assert res.total_return == np.inf
    assert res.annual_return == 0.0


# ---------------------------------------------------------------------------
# btc_overlay_profiles
# ---------------------------------------------------------------------------


def test_get_profile_unknown_raises() -> None:
    from quantflow.strategy.research.btc_overlay_profiles import (
        get_profile,
        primary_eval_kwargs,
    )

    with pytest.raises(KeyError, match="unknown profile"):
        get_profile("not_a_profile")
    assert get_profile("primary_w30")["name"] == "primary_w30"
    kw = primary_eval_kwargs()
    assert kw["overlay_weight"] == 0.30


# ---------------------------------------------------------------------------
# backtest._periods_per_year
# ---------------------------------------------------------------------------


def test_periods_per_year_median_fallback(monkeypatch) -> None:
    """to_offset returns None -> median-delta path (279->284)."""
    from quantflow.strategy.research.backtest import BacktestEngine

    monkeypatch.setattr(pd.tseries.frequencies, "to_offset", lambda x: None)
    idx = pd.date_range("2024-01-01", periods=10, freq="h")
    assert BacktestEngine._periods_per_year(idx) == pytest.approx(8760.0)


def test_periods_per_year_to_offset_raises(monkeypatch) -> None:
    """to_offset raising -> except -> median path (281-282)."""
    from quantflow.strategy.research.backtest import BacktestEngine

    def boom(_x):
        raise ValueError("bad freq")

    monkeypatch.setattr(pd.tseries.frequencies, "to_offset", boom)
    idx = pd.date_range("2024-01-01", periods=10, freq="h")
    assert BacktestEngine._periods_per_year(idx) == pytest.approx(8760.0)


def test_periods_per_year_single_bar(caplog) -> None:
    """len(index) < 2 -> fallback warning -> 365 (285->298)."""
    from quantflow.strategy.research.backtest import BacktestEngine

    idx = pd.Index([pd.Timestamp("2024-01-01")])
    with caplog.at_level("WARNING"):
        assert BacktestEngine._periods_per_year(idx) == 365.0
    assert "Could not infer bar frequency" in caplog.text


def test_periods_per_year_all_nat_deltas(caplog) -> None:
    """deltas empty after dropna -> fallback warning (287->298)."""
    from quantflow.strategy.research.backtest import BacktestEngine

    idx = pd.Index([pd.Timestamp("2024-01-01"), pd.NaT])
    with caplog.at_level("WARNING"):
        assert BacktestEngine._periods_per_year(idx) == 365.0
    assert "Could not infer bar frequency" in caplog.text


def test_periods_per_year_zero_median_delta(caplog) -> None:
    """median delta 0 -> not > 0 -> fallback warning (289->298)."""
    from quantflow.strategy.research.backtest import BacktestEngine

    idx = pd.Index([pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-01")])
    with caplog.at_level("WARNING"):
        assert BacktestEngine._periods_per_year(idx) == 365.0
    assert "Could not infer bar frequency" in caplog.text


def test_periods_per_year_diff_raises(caplog) -> None:
    """diff() on non-numeric index -> except path (291-292)."""
    from quantflow.strategy.research.backtest import BacktestEngine

    with caplog.at_level("WARNING"):
        assert BacktestEngine._periods_per_year(pd.Index(["a", "b"])) == 365.0
    assert "Could not infer bar frequency" in caplog.text


# ---------------------------------------------------------------------------
# optimizer
# ---------------------------------------------------------------------------


def test_optimizer_grid_candidates_zero_trials() -> None:
    from quantflow.strategy.research.optimizer import StrategyOptimizer

    assert StrategyOptimizer._grid_candidates({"a": (1, 5)}, n_trials=0) == []
    assert StrategyOptimizer._grid_values((), 5) == []
    assert StrategyOptimizer._grid_values((1,), 5) == [1]
    # int range whose step does not land on high -> append high (line 230)
    assert StrategyOptimizer._grid_values((1, 9), 4) == [1, 4, 7, 9]


def test_optimizer_evaluate_params_non_finite(monkeypatch) -> None:
    from quantflow.strategy.research.optimizer import StrategyOptimizer

    close = pd.Series([1.0, 2.0, 3.0])

    def sig(c, **p):
        return (pd.Series(False, index=c.index), pd.Series(False, index=c.index))

    monkeypatch.setattr(
        StrategyOptimizer, "_objective_value", staticmethod(lambda r, o: float("nan"))
    )
    v = StrategyOptimizer()._evaluate_params(close, sig, {}, 10000.0, 0.001, "sharpe", "test")
    assert v == -10.0


# ---------------------------------------------------------------------------
# elliott_wave_wfo_smoke
# ---------------------------------------------------------------------------


def _wave_df(n: int = 300) -> pd.DataFrame:
    from quantflow.strategy.research.elliott_wave_backtest import (
        generate_synthetic_wave_data,
    )

    return generate_synthetic_wave_data(n_bars=n)


def test_load_parquet_ohlcv_missing(monkeypatch) -> None:
    from quantflow import data as data_pkg
    from quantflow.strategy.research import elliott_wave_wfo_smoke as wfo

    class EmptyStore:
        def __init__(self, *a, **k):
            pass

        def query(self, *a, **k):
            return None

    monkeypatch.setattr(data_pkg.store, "DataStore", EmptyStore)
    with pytest.raises(FileNotFoundError, match="No OHLCV"):
        wfo._load_parquet_ohlcv("BTC/USDT", "x")


def test_load_parquet_ohlcv_missing_column(monkeypatch) -> None:
    from quantflow import data as data_pkg
    from quantflow.strategy.research import elliott_wave_wfo_smoke as wfo

    class NoVolStore:
        def __init__(self, *a, **k):
            pass

        def query(self, *a, **k):
            return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0]})

    monkeypatch.setattr(data_pkg.store, "DataStore", NoVolStore)
    with pytest.raises(ValueError, match="missing column"):
        wfo._load_parquet_ohlcv("BTC/USDT", "x")


def test_load_parquet_ohlcv_ok(monkeypatch) -> None:
    from quantflow import data as data_pkg
    from quantflow.strategy.research import elliott_wave_wfo_smoke as wfo

    df = _wave_df(60)

    class GoodStore:
        def __init__(self, *a, **k):
            pass

        def query(self, *a, **k):
            return df

    monkeypatch.setattr(data_pkg.store, "DataStore", GoodStore)
    out = wfo._load_parquet_ohlcv("BTC/USDT", "x", start=1, end=2)
    assert len(out) == 60


def test_run_elliott_wfo_smoke_parquet_path(monkeypatch) -> None:
    from quantflow.strategy.research import elliott_wave_wfo_smoke as wfo

    df = _wave_df(120)
    monkeypatch.setattr(wfo, "_load_parquet_ohlcv", lambda *a, **k: df)
    rep = wfo.run_elliott_wfo_smoke(parquet_dir="x", symbol="BTC/USDT", n_windows=2)
    assert rep.data_source.startswith("parquet:")
    assert rep.n_bars == 120


def test_run_elliott_wfo_smoke_synthetic_default() -> None:
    """No df and no parquet_dir -> synthetic fallback (120-121)."""
    from quantflow.strategy.research import elliott_wave_wfo_smoke as wfo

    rep = wfo.run_elliott_wfo_smoke(n_bars=60, n_windows=2)
    assert rep.data_source == "synthetic"
    assert rep.n_bars == 60


def test_run_elliott_wfo_smoke_short_series() -> None:
    from quantflow.strategy.research import elliott_wave_wfo_smoke as wfo

    short = _wave_df(50)
    rep = wfo.run_elliott_wfo_smoke(df=short, n_windows=2)
    assert any("short series" in n for n in rep.notes)


def test_oos_metrics_entry_exit_and_eod() -> None:
    from quantflow.strategy.research import elliott_wave_wfo_smoke as wfo

    close = [100.0, 101.0, 102.0, 103.0, 104.0]
    df = pd.DataFrame({"close": close})
    entries = pd.Series([True, False, False, False, True], dtype=bool)
    exits = pd.Series([False, False, True, False, False], dtype=bool)
    m = wfo._oos_metrics(df, entries, exits)
    assert m["total_trades"] == 2  # mid exit + end-of-series force close
    assert m["sharpe_ratio"] > 0  # line 218 sharpe branch


def test_run_full_series_smoke() -> None:
    from quantflow.strategy.research import elliott_wave_wfo_smoke as wfo

    out = wfo.run_full_series_smoke(df=_wave_df(120), n_windows=2)
    assert "full_series" in out and "wfo_smoke" in out
    assert out["wfo_smoke"]["n_bars"] == 120


# ---------------------------------------------------------------------------
# elliott_paper_replay_contract / elliott_cost_grid_contract
# ---------------------------------------------------------------------------


def _wave_df_with_ts(n: int = 120) -> pd.DataFrame:
    df = _wave_df(n)
    df["timestamp"] = [i * 3_600_000 for i in range(n)]
    return df


@pytest.mark.asyncio
async def test_build_elliott_paper_replay_package_with_df() -> None:
    from quantflow.strategy.research.elliott_paper_replay_contract import (
        build_elliott_paper_replay_package,
    )

    pkg = await build_elliott_paper_replay_package(df=_wave_df_with_ts(100))
    assert pkg.n_bars == 100
    assert pkg.execution_path == "paper_replay"
    assert pkg.promotion_eligible is False
    assert "data_source=provided_df" in pkg.notes


@pytest.mark.asyncio
async def test_build_cost_grid_package_proxy_with_df(monkeypatch, tmp_path) -> None:
    from quantflow.strategy.research import elliott_cost_grid_contract as egc

    def boom(report):
        raise ValueError("missing cost grid")

    monkeypatch.setattr(egc, "require_cost_grid", boom)
    pkg = await egc.build_elliott_cost_grid_package(
        df=_wave_df_with_ts(80), reseat=False, output_dir=tmp_path
    )
    d = pkg.to_dict()  # ElliottCostGridPackage.to_dict
    assert d["promotion_eligible"] is False
    assert pkg.cost_check["passed"] is False
    assert any("missing cost grid" in r for r in pkg.cost_check["reasons"])
    assert pkg.output_dir is not None
    assert (tmp_path / "summary.json").is_file()


@pytest.mark.asyncio
async def test_build_cost_grid_package_funding_check_raises(monkeypatch) -> None:
    from quantflow.strategy.research import elliott_cost_grid_contract as egc

    def boom(report):
        raise ValueError("missing funding tca")

    monkeypatch.setattr(egc, "require_funding_tca", boom)
    pkg = await egc.build_elliott_cost_grid_package(df=_wave_df_with_ts(80), reseat=False)
    assert pkg.cost_check["passed"] is False
    assert any("missing funding tca" in r for r in pkg.cost_check["reasons"])
    assert pkg.report["decision"] == "NO_GO"


@pytest.mark.asyncio
async def test_build_cost_grid_package_synthetic_no_ts() -> None:
    """df=None -> synthetic frame; no timestamp -> added (lines 186, 190)."""
    from quantflow.strategy.research import elliott_cost_grid_contract as egc

    pkg = await egc.build_elliott_cost_grid_package(n_bars=60, reseat=False)
    assert pkg.report["run_meta"]["n_bars"] == 60
    assert pkg.report["run_meta"]["cost_grid_method"] == "proxy_from_fills"


@pytest.mark.asyncio
async def test_build_cost_grid_package_reseat() -> None:
    """reseat=True -> _reseat_grid_from_replays (114-148) + 197-200."""
    from quantflow.strategy.research import elliott_cost_grid_contract as egc

    pkg = await egc.build_elliott_cost_grid_package(df=_wave_df_with_ts(90), reseat=True)
    assert pkg.report["run_meta"]["cost_grid_method"] == "paper_replay_reseat"
    assert pkg.cost_check["passed"] is True
    assert pkg.report["decision"] == "NO_GO"
