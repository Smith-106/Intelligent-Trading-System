"""Additional tests for walk-forward optimization helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from quantflow.strategy.validation.wfo import WalkForwardOptimization, walk_forward_optimization


def _close_series(n: int = 12) -> pd.Series:
    return pd.Series(range(100, 100 + n), index=pd.RangeIndex(n), dtype=float)


def _signal_series(n: int = 12) -> tuple[pd.Series, pd.Series]:
    entries = pd.Series(False, index=pd.RangeIndex(n))
    exits = pd.Series(False, index=pd.RangeIndex(n))
    if n > 3:
        entries.iloc[0] = True
        exits.iloc[2] = True
    if n > 8:
        entries.iloc[5] = True
        exits.iloc[7] = True
    return entries, exits


class TestWalkForwardOptimizationClass:
    def test_run_returns_error_when_no_valid_folds(self) -> None:
        close = _close_series(5)
        entries, exits = _signal_series(5)
        wfo = WalkForwardOptimization(n_folds=5, test_ratio=0.9, purge_delta=10)

        result = wfo.run(close, entries, exits)

        assert result.folds == []
        assert result.passed is False
        # ISS-028: details now reports skipped fold count so the effective fold
        # count is visible, not silently reduced.
        assert result.details["error"] == "no valid folds produced"
        assert result.details["skipped_folds"] == 5
        assert result.details["configured_n_folds"] == 5

    def test_run_uses_optimize_fn_and_aggregates_fold_metrics(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        close = _close_series(20)
        entries, exits = _signal_series(20)
        wfo = WalkForwardOptimization(
            n_folds=4, test_ratio=0.4, anchored=True, degradation_threshold=0.6
        )
        optimize_calls: list[int] = []
        sharpe_values = iter([2.0, 1.5, 1.0, 0.8, 3.0, 1.8])
        return_values = iter([0.2, 0.1, 0.15, 0.05, 0.3, 0.12])

        def fake_optimize(train_close: pd.Series):
            optimize_calls.append(len(train_close))
            size = len(train_close)
            return (
                pd.Series(False, index=train_close.index),
                pd.Series(False, index=train_close.index),
                {"window": size},
            )

        monkeypatch.setattr(wfo, "_compute_sharpe", lambda *args: next(sharpe_values))
        monkeypatch.setattr(wfo, "_compute_return", lambda *args: next(return_values))

        result = wfo.run(close, entries, exits, optimize_fn=fake_optimize)

        assert optimize_calls == [5, 10]
        assert len(result.folds) == 2
        assert result.folds[0].best_params == {"window": 5}
        assert result.mean_train_sharpe == pytest.approx((2.0 + 1.0) / 2)
        assert result.mean_test_sharpe == pytest.approx((1.5 + 0.8) / 2)
        assert result.total_test_return == pytest.approx(0.1 + 0.05)
        assert result.passed is True

    def test_run_sets_degradation_zero_when_mean_train_is_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        close = _close_series(20)
        entries, exits = _signal_series(20)
        wfo = WalkForwardOptimization(
            n_folds=4, test_ratio=0.4, anchored=False, degradation_threshold=0.1
        )
        sharpe_values = iter([0.0, 1.0, 0.0, 0.5, 0.0, -0.5])
        return_values = iter([0.0, 0.1, 0.0, 0.1, 0.0, 0.1])

        monkeypatch.setattr(wfo, "_compute_sharpe", lambda *args: next(sharpe_values))
        monkeypatch.setattr(wfo, "_compute_return", lambda *args: next(return_values))

        result = wfo.run(close, entries, exits)

        assert result.mean_train_sharpe == 0.0
        assert result.degradation == 0.0
        assert result.passed is False

    def test_run_without_optimize_fn_uses_input_signals_and_empty_best_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        close = _close_series(20)
        entries, exits = _signal_series(20)
        wfo = WalkForwardOptimization(
            n_folds=4, test_ratio=0.4, anchored=True, degradation_threshold=0.1
        )
        sharpe_values = iter([1.0, 0.8, 1.2, 0.7])
        return_values = iter([0.1, 0.05, 0.2, 0.08])

        monkeypatch.setattr(wfo, "_compute_sharpe", lambda *args: next(sharpe_values))
        monkeypatch.setattr(wfo, "_compute_return", lambda *args: next(return_values))

        result = wfo.run(close, entries, exits)

        assert len(result.folds) == 2
        assert all(fold.best_params == {} for fold in result.folds)

    def test_compute_sharpe_handles_empty_flat_and_variable_returns(self) -> None:
        close = pd.Series([100.0, 110.0, 120.0, 132.0, 144.0], index=pd.RangeIndex(5))
        entries = pd.Series([False, False, False, False, False], index=close.index)
        exits = pd.Series([False, False, False, False, False], index=close.index)

        assert WalkForwardOptimization._compute_sharpe(close, entries, exits) == 0.0

        entries.iloc[0] = True
        exits.iloc[1] = True
        entries.iloc[2] = True
        exits.iloc[3] = True
        assert WalkForwardOptimization._compute_sharpe(close, entries, exits) == 0.0

        close2 = pd.Series([100.0, 120.0, 121.0, 100.0, 140.0], index=pd.RangeIndex(5))
        sharpe = WalkForwardOptimization._compute_sharpe(close2, entries, exits)
        assert sharpe != 0.0

    def test_compute_return_sums_closed_trades(self) -> None:
        close = pd.Series([100.0, 110.0, 120.0, 90.0, 99.0], index=pd.RangeIndex(5))
        entries = pd.Series([True, False, True, False, False], index=close.index)
        exits = pd.Series([False, True, False, True, False], index=close.index)

        total_return = WalkForwardOptimization._compute_return(close, entries, exits)

        expected = (120.0 - 110.0) / 110.0 + (99.0 - 90.0) / 90.0
        assert total_return == pytest.approx(expected)


class TestWalkForwardOptimizationFunction:
    def test_function_interface_optimizes_train_window_and_recomputes_oos_signals(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        close = _close_series(18)
        entries, exits = _signal_series(18)
        df = pd.DataFrame({"close": close, "volume": 1.0}, index=close.index)
        calls: list[tuple[str, int, dict[str, object]]] = []

        class FakeOptimizer:
            def __init__(self, engine=None) -> None:
                self.engine = engine

            def optimize(self, close, signal_fn, param_space, **kwargs):
                train_entries, _ = signal_fn(close, threshold=2)
                calls.append(("optimize", len(close), dict(param_space)))
                assert train_entries.index.equals(close.index)
                return {"best_params": {"threshold": 2}}

        class FakeEngine:
            def run_backtest(self, close_slice, entries_slice, exits_slice, initial_capital, fee):
                if len(close_slice) == 0:
                    raise RuntimeError("empty slice")
                return SimpleNamespace(
                    sharpe_ratio=1.0 if bool(entries_slice.any()) else 0.1,
                    total_return=0.2 if bool(entries_slice.any()) else 0.0,
                    max_drawdown=-0.01,
                    num_trades=int(entries_slice.sum()),
                )

        def signal_fn(frame: pd.DataFrame, **params):
            calls.append(("signal", len(frame), dict(params)))
            threshold = int(params["threshold"])
            generated_entries = frame["close"] % threshold == 0
            generated_exits = pd.Series(False, index=frame.index)
            return generated_entries, generated_exits

        monkeypatch.setattr(
            "quantflow.strategy.research.optimizer.StrategyOptimizer", FakeOptimizer
        )
        monkeypatch.setattr("quantflow.strategy.research.backtest.BacktestEngine", FakeEngine)

        result = walk_forward_optimization(
            close,
            entries,
            exits,
            n_windows=3,
            mode="rolling",
            oos_ratio=0.5,
            signal_fn=signal_fn,
            param_space={"threshold": (2, 3)},
            data=df,
            n_trials=2,
        )

        assert result["optimized"] is True
        assert result["oos_recomputed"] is True
        assert all(window["best_params"] == {"threshold": 2} for window in result["window_results"])
        assert "precision" in result["signal_quality"]
        assert any(kind == "optimize" for kind, _, _ in calls)
        assert any(kind == "signal" and params == {"threshold": 2} for kind, _, params in calls)

    def test_function_interface_handles_is_and_oos_exceptions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        close = _close_series(12)
        entries, exits = _signal_series(12)

        class FakeEngine:
            def __init__(self) -> None:
                self.calls = 0

            def run_backtest(self, close_slice, entries_slice, exits_slice, initial_capital, fee):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("is failed")
                if self.calls == 2:
                    raise RuntimeError("oos failed")
                return SimpleNamespace(
                    sharpe_ratio=0.8,
                    total_return=0.12,
                    max_drawdown=-0.03,
                    num_trades=4,
                )

        monkeypatch.setattr("quantflow.strategy.research.backtest.BacktestEngine", FakeEngine)

        result = walk_forward_optimization(
            close, entries, exits, n_windows=2, mode="rolling", oos_ratio=0.5
        )

        assert result["n_windows"] == 2
        assert result["window_results"][0]["is_sharpe"] == 0.0
        assert result["window_results"][0]["oos_sharpe"] == 0.0
        assert result["window_results"][0]["oos_trades"] == 0
        assert result["window_results"][1]["oos_return"] == pytest.approx(0.12)

    def test_function_interface_supports_zero_length_oos_windows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        close = _close_series(10)
        entries, exits = _signal_series(10)

        class FakeEngine:
            def run_backtest(self, close_slice, entries_slice, exits_slice, initial_capital, fee):
                return SimpleNamespace(
                    sharpe_ratio=1.0,
                    total_return=0.05,
                    max_drawdown=-0.01,
                    num_trades=1,
                )

        monkeypatch.setattr("quantflow.strategy.research.backtest.BacktestEngine", FakeEngine)

        result = walk_forward_optimization(
            close, entries, exits, n_windows=6, mode="anchored", oos_ratio=0.6
        )

        assert result["n_windows"] == 6
        assert result["mode"] == "anchored"
        assert result["decision"] in {"GO", "NO-GO"}
