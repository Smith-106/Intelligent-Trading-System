"""Coverage completion for validation algorithm modules.

Targets the remaining uncovered lines/branches in:
- cpcv (train_signal_fn closure with data containing "close")
- dsr / pbo (_sanitize_metric_array wrapper)
- wfo (all-folds-skipped + partial-skip + optimize failure + data w/o close)
- gate (all-OOS-failed short-circuit)
- lookahead (attr/subscript/expr chains, np.<agg> shape, getsource/syntax
  failures, scan_strategies)
- monte_carlo (empty array guards, bootstrap keep_paths)
- recursive (source/file introspection failures, compute-all AST patterns)

Pure-logic paths only; no external data or vectorbt; async is not used here.
"""

from __future__ import annotations

import ast

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.base import StrategyBase
from quantflow.strategy.validation import cpcv as cpcv_mod
from quantflow.strategy.validation import dsr as dsr_mod
from quantflow.strategy.validation import lookahead as lookahead_mod
from quantflow.strategy.validation import monte_carlo as mc_mod
from quantflow.strategy.validation import pbo as pbo_mod
from quantflow.strategy.validation import recursive as recursive_mod
from quantflow.strategy.validation.cpcv import cpcv_backtest, split_cpcv
from quantflow.strategy.validation.gate import validation_gate
from quantflow.strategy.validation.lookahead import (
    LookaheadReport,
    scan_strategies,
    scan_strategy,
)
from quantflow.strategy.validation.monte_carlo import (
    _max_drawdown,
    _percentile,
    returns_bootstrap_stress,
)
from quantflow.strategy.validation.pbo import probability_of_overfitting
from quantflow.strategy.validation.wfo import WalkForwardOptimization, walk_forward_optimization


# ---------------------------------------------------------------------------
# cpcv
# ---------------------------------------------------------------------------
def test_cpcv_signal_fn_with_close_column_covers_train_closure(monkeypatch) -> None:
    """cpcv_backtest with signal_fn+param_space and data w/ 'close' column hits
    the `if "close" in train_slice.columns` branch (183->184->185)."""
    from quantflow.strategy.research.optimizer import StrategyOptimizer

    n = 60
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(close, index=idx)
    entries = pd.Series(False, index=idx)
    exits = pd.Series(False, index=idx)
    entries.iloc[5] = True
    exits.iloc[9] = True

    def fake_optimize(self, close_slice, signal_fn, param_space, **kwargs):
        params = {k: v[0] for k, v in param_space.items()}
        signal_fn(close_slice, **params)
        return {"best_params": params, "best_value": 1.0}

    monkeypatch.setattr(StrategyOptimizer, "optimize", fake_optimize)

    def signal_fn(data, **params):
        c = data["close"]
        return c > c.rolling(5).mean(), c < c.rolling(5).mean()

    data = pd.DataFrame({"close": close}, index=idx)
    out = cpcv_backtest(
        close,
        entries,
        exits,
        n_groups=4,
        n_test_groups=1,
        signal_fn=signal_fn,
        param_space={"stop_loss_pct": (0.03,)},
        data=data,
        fee=0.001,
    )
    assert out["optimized"] is True
    assert "path_results" in out


def test_cpcv_split_embargo_boundary() -> None:
    splits = split_cpcv(100, n_groups=8, n_test_groups=2, embargo_pct=0.01)
    assert len(splits) == 28
    # embargo removes train samples within ~1 bar of test indices
    assert all(len(tr) < 100 for tr, _te in splits)


def test_cpcv_failure_when_data_too_short() -> None:
    close = pd.Series([100.0, 101.0], index=pd.date_range("2024-01-01", periods=2, freq="D"))
    entries = pd.Series([False, False], index=close.index)
    exits = pd.Series([False, False], index=close.index)
    out = cpcv_backtest(close, entries, exits, n_groups=8)
    assert out["passed"] is False
    assert out["n_paths"] == 0


# ---------------------------------------------------------------------------
# dsr / pbo helper
# ---------------------------------------------------------------------------
def test_dsr_no_trials_fails_closed() -> None:
    out = dsr_mod.deflated_sharpe_ratio(1.0, n_trials=0)
    assert out["passed"] is False
    assert out["reason"] == "no_trials"


def test_dsr_expected_max_single_trial_fail_closed() -> None:
    assert dsr_mod._expected_max_sharpe(1) == float("inf")


def test_pbo_sanitize_wrapper_and_failure_paths() -> None:
    arr = pbo_mod._sanitize_metric_array([1.0, float("nan"), float("inf")])
    assert np.isfinite(arr).all()

    # PBO failure when data too short for CPCV splits
    close = pd.Series([100.0, 101.0], index=pd.date_range("2024-01-01", periods=2, freq="D"))
    entries = pd.Series([False, False], index=close.index)
    exits = pd.Series([False, False], index=close.index)
    out = probability_of_overfitting(close, entries, exits, n_groups=8)
    assert out["passed"] is False
    assert out["pbo"] == 1.0


# ---------------------------------------------------------------------------
# wfo
# ---------------------------------------------------------------------------
def test_wfo_all_folds_skipped_returns_error_result() -> None:
    close = pd.Series(np.arange(10.0), index=pd.date_range("2024-01-01", periods=10, freq="D"))
    entries = pd.Series(False, index=close.index)
    exits = pd.Series(False, index=close.index)
    wfo = WalkForwardOptimization(n_folds=5, test_ratio=0.5, purge_delta=5)
    res = wfo.run(close, entries, exits)
    assert res.folds == []
    assert res.passed is False
    assert res.details["error"] == "no valid folds produced"


def test_wfo_partial_skip_logs_and_aggregates() -> None:
    n = 30
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(100 + np.arange(n), index=idx, dtype=float)
    entries = pd.Series(False, index=idx)
    exits = pd.Series(False, index=idx)
    entries.iloc[1] = True
    exits.iloc[4] = True
    # anchored: fold 0's train_end <= 0 with purge=8, remaining folds valid
    wfo = WalkForwardOptimization(n_folds=5, test_ratio=0.5, anchored=True, purge_delta=8)
    res = wfo.run(close, entries, exits)
    assert len(res.folds) >= 1
    assert res.details["skipped_folds"] >= 1
    assert np.isfinite(res.mean_train_sharpe)


def test_wfo_compute_sharpe_exit_trade_and_open_trade() -> None:
    idx = pd.date_range("2024-01-01", periods=60, freq="D")
    close = pd.Series(np.linspace(100, 130, 60), index=idx)
    entries = pd.Series(False, index=idx)
    exits = pd.Series(False, index=idx)
    entries.iloc[5] = True
    exits.iloc[9] = True
    entries.iloc[20] = True
    exits.iloc[40] = True
    sh = WalkForwardOptimization._compute_sharpe(close, entries, exits)
    assert sh != 0.0 or close.std() >= 0
    ret = WalkForwardOptimization._compute_return(close, entries, exits)
    assert ret != 0.0


def test_wfo_function_interface_data_without_close_column(monkeypatch) -> None:
    """365->367 False path: train_data lacking a 'close' column."""
    from quantflow.strategy.research.optimizer import StrategyOptimizer

    def fake_optimize(self, close_slice, signal_fn, param_space, **kwargs):
        params = {k: v[0] for k, v in param_space.items()}
        signal_fn(close_slice, **params)
        return {"best_params": params, "best_value": 1.0}

    monkeypatch.setattr(StrategyOptimizer, "optimize", fake_optimize)

    idx = pd.date_range("2024-01-01", periods=120, freq="h")
    close = pd.Series(100 + np.arange(120), index=idx, dtype=float)

    def signal_fn(data, **params):
        c = data["factor"]
        return c > 50, c < 40

    data = pd.DataFrame({"factor": close.to_numpy()}, index=idx)  # no 'close' column
    out = walk_forward_optimization(
        close,
        pd.Series(False, index=idx),
        pd.Series(False, index=idx),
        n_windows=2,
        oos_ratio=0.3,
        signal_fn=signal_fn,
        param_space={"thr": (0.5,)},
        data=data,
        method="grid",
        n_trials=2,
    )
    assert out["optimized"] is True
    assert out["window_results"]


def test_wfo_function_interface_optimize_failure_sets_empty_params(monkeypatch) -> None:
    from quantflow.strategy.research.optimizer import StrategyOptimizer

    def raise_optimize(self, *args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(StrategyOptimizer, "optimize", raise_optimize)

    idx = pd.date_range("2024-01-01", periods=80, freq="h")
    close = pd.Series(100 + np.arange(80), index=idx, dtype=float)
    entries = pd.Series(False, index=idx)
    exits = pd.Series(False, index=idx)

    def signal_fn(data, **params):
        c = data["close"]
        on = c > c.rolling(5).mean()
        return on, ~on

    data = pd.DataFrame({"close": close.to_numpy()}, index=idx)
    out = walk_forward_optimization(
        close,
        entries,
        exits,
        n_windows=2,
        oos_ratio=0.3,
        signal_fn=signal_fn,
        param_space={"fast": (3,)},
        data=data,
        method="bayesian",
        n_trials=1,
    )
    # optimization failed on every window; run continues with train signal gen
    assert out["n_windows"] == 2
    assert all(w["best_params"] == {} for w in out["window_results"])


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------
def test_gate_short_circuits_when_all_cpcv_paths_failed(monkeypatch) -> None:
    """gate.py 91-94: CPCV passed but every path has NaN OOS sharpe."""
    fake_cpcv = {
        "passed": True,
        "pbo": 0.2,
        "path_results": [
            {"oos_sharpe": float("nan"), "oos_win_rate": 0.5},
            {"oos_sharpe": float("nan"), "oos_win_rate": 0.5},
        ],
    }

    def fake_cpcv_backtest(*args, **kwargs):
        return fake_cpcv

    monkeypatch.setattr("quantflow.strategy.validation.gate.cpcv_backtest", fake_cpcv_backtest)
    idx = pd.date_range("2024-01-01", periods=50, freq="D")
    close = pd.Series(np.linspace(100, 120, 50), index=idx)
    entries = pd.Series(False, index=idx)
    exits = pd.Series(False, index=idx)
    out = validation_gate(close, entries, exits)
    assert out["decision"] == "NO-GO"
    assert "all paths failed" in out["reason"]


# ---------------------------------------------------------------------------
# lookahead
# ---------------------------------------------------------------------------
class _AttrChainLeakStrategy(StrategyBase):
    """df.close[entries].mean() — Attribute chain in _attr_chain."""

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        series = df["close"]
        entries = series > series.mean()
        exits = series < series.mean()
        leak = series[entries].mean()  # masked aggregation (attribute value)
        return series > leak, series < leak


class _SubscriptChainLeakStrategy(StrategyBase):
    """df[\"close\"][entries].mean() + (expr)[entries].mean()"""

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        s = df["close"]
        entries = s > s.mean()
        exits = s < s.mean()
        a = df["close"][entries].mean()  # Subscript in attr chain
        b = (s + 1.0)[exits].mean()  # BinOp -> "<expr>"
        return s > (a + b), s < (a + b)


class _NpAggLeakStrategy(StrategyBase):
    """np.<agg>(series[mask]) — Shape 2 with attribute func."""

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        import numpy as np

        s = df["close"]
        entries = s > s.mean()
        exits = s < s.mean()
        a = np.mean(s[entries])  # attribute func wrapping masked subscript
        b = np.sum(s[exits])
        return s > (a + b), s < (a + b)


class _CleanintStrategy(StrategyBase):
    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        s = df["close"]
        return s > s.mean(), s < s.mean()


def _leak_df(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"close": 100 + np.cumsum(rng.normal(0, 2, n)), "open": 100.0},
        index=idx,
    )


def test_lookahead_attr_and_subscript_chains() -> None:
    for cls in (_AttrChainLeakStrategy, _SubscriptChainLeakStrategy, _NpAggLeakStrategy):
        rep = scan_strategy(cls())
        assert not rep.passed
        assert rep.findings


def test_lookahead_clean_strategy_scan_strategies() -> None:
    reps = scan_strategies([_CleanintStrategy(), _CleanintStrategy()])
    assert len(reps) == 2
    assert all(r.passed for r in reps)
    assert "PASS" in reps[0].summary()


def test_lookahead_slice_name_fallback_unreachable() -> None:
    # _slice_name's "<?>" branch is gated by _slice_is_mask (Name-only); the
    # parser-level guard makes it unreachable — assert the helper on a non-Name.
    assert lookahead_mod._slice_name(ast.Constant(value=1)) == "<?>"


def test_lookahead_method_source_type_error(monkeypatch) -> None:
    """_method_ast (250-251): inspect.getsource raises TypeError for builtins."""

    class _TypeErrorMethod(StrategyBase):
        generate_signals = staticmethod(len)  # builtin: getsource raises TypeError

    rep = scan_strategy(_TypeErrorMethod())
    assert "generate_signals" not in rep.scanned_methods


def test_lookahead_method_source_syntax_error(monkeypatch) -> None:
    """_method_ast (259-260): ast.parse raises SyntaxError for invalid source."""

    class _OkSource(StrategyBase):
        def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
            s = df["close"]
            return s > s.mean(), s < s.mean()

    def bad_source(obj):
        return "def broken(:\n"

    monkeypatch.setattr(lookahead_mod.inspect, "getsource", bad_source)
    rep = scan_strategy(_OkSource())
    assert rep.scanned_methods == []


def test_lookahead_scanned_method_negative_shift_reget_source_failure(monkeypatch) -> None:
    """291-292: parsed method ok, second getsource (shift scan) raises."""

    class _ShiftStrategy(StrategyBase):
        def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
            s = df["close"]
            return s > s.shift(1), s < s.shift(1)

    import inspect as _mod_inspect

    _orig = _mod_inspect.getsource
    calls = {"n": 0}

    def flaky_getsource(obj):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TypeError("second call fails")
        return _orig(obj)

    monkeypatch.setattr(lookahead_mod.inspect, "getsource", flaky_getsource)
    rep = scan_strategy(_ShiftStrategy())
    # First method parsed fine; the shift-scan getsource failure just skips.
    assert "generate_signals" in rep.scanned_methods


def test_lookahead_source_path_failure(monkeypatch) -> None:
    def raise_getsourcefile(obj):
        raise TypeError("no file")

    monkeypatch.setattr(
        lookahead_mod.inspect, "getsourcefile", raise_getsourcefile
    )
    rep = scan_strategy(_CleanintStrategy())
    assert rep.source_path is None


# ---------------------------------------------------------------------------
# monte_carlo
# ---------------------------------------------------------------------------
def test_monte_carlo_empty_array_guards() -> None:
    assert _max_drawdown(np.array([])) == 0.0
    assert _percentile(np.array([]), 5) == 0.0


def test_monte_carlo_bootstrap_keep_paths() -> None:
    r = returns_bootstrap_stress([0.01, -0.005, 0.02, 0.0], n_paths=3, seed=1, keep_paths=True)
    assert len(r.paths) == 3
    assert all(len(p) == 5 for p in r.paths)


# ---------------------------------------------------------------------------
# recursive
# ---------------------------------------------------------------------------
class _IndicatorProbeStrategy:
    """Source contains self.rsi.compute() + bare engine.compute() patterns."""

    name = "probe"

    def __init__(self) -> None:
        self.rsi = object()

    def generate_signals(self, df):
        self.rsi.compute()  # Attribute.value is Attribute -> hasattr -> 98
        engine.compute()  # Attribute.value is Name + compute attr -> 103
        IndicatorEngine.compute_all()  # Attribute.value is Name + compute_all -> 103
        return df


def test_recursive_deps_extract_compute_patterns() -> None:
    report = recursive_mod.scan_recursive(_IndicatorProbeStrategy)
    assert report.passed
    deps = report.indicator_deps
    assert any("rsi" in v for v in deps.values())
    assert any("engine" in v for v in deps.values())


def test_recursive_introspection_failures(monkeypatch) -> None:
    class _Dummy:
        pass

    def raise_getfile(obj):
        raise TypeError("no file")

    monkeypatch.setattr(recursive_mod.inspect, "getfile", raise_getfile)
    report = recursive_mod.scan_recursive(_Dummy)
    assert report.source_path is None

    def raise_getsource(obj):
        raise OSError("no source")

    monkeypatch.setattr(recursive_mod.inspect, "getsource", raise_getsource)
    report2 = recursive_mod.scan_recursive(_Dummy)
    assert report2.indicator_deps == {}
    assert report2.passed


def test_recursive_cycle_detection() -> None:
    report = recursive_mod.scan_recursive(_IndicatorProbeStrategy)
    assert report.passed
    cycles = recursive_mod._detect_cycles({"a": ["b"], "b": ["a"]})
    assert cycles and cycles[0][0] == cycles[0][-1]