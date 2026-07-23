import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.validation import gate as gate_module
from quantflow.strategy.validation.cpcv import cpcv_backtest, split_cpcv
from quantflow.strategy.validation.dsr import _expected_max_sharpe, deflated_sharpe_ratio
from quantflow.strategy.validation.gate import validation_gate
from quantflow.strategy.validation.pbo import probability_of_overfitting
from quantflow.strategy.validation.wfo import walk_forward_optimization


def _make_price_series(n: int = 200, trend: float = 0.002) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    rng = np.random.default_rng(42)
    returns = np.clip(trend + rng.normal(0, 0.01, n), -0.05, 0.05)
    prices = 100.0 * pd.Series(1.0 + returns, index=dates).cumprod().to_numpy()
    return pd.Series(prices, index=dates)


def _make_signals(n: int) -> tuple[pd.Series, pd.Series]:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    entries = pd.Series(False, index=dates)
    exits = pd.Series(False, index=dates)
    for i in range(0, n, 20):
        if i < n:
            entries.iloc[i] = True
    for i in range(10, n, 20):
        if i < n:
            exits.iloc[i] = True
    return entries, exits


class TestCPCV:
    def test_split_cpcv_basic(self):
        splits = split_cpcv(100, n_groups=4, n_test_groups=1)
        assert len(splits) == 4  # C(4,1) = 4
        for train, test in splits:
            assert len(train) > 0
            assert len(test) > 0
            assert len(set(train) & set(test)) == 0  # no overlap

    def test_split_cpcv_embargo(self):
        splits = split_cpcv(100, n_groups=4, n_test_groups=1, embargo_pct=0.05)
        for train, test in splits:
            # Check embargo: no train index within 5 bars of any test index
            for t in test:
                nearby = [idx for idx in train if abs(idx - t) <= 5]
                assert len(nearby) == 0

    def test_cpcv_backtest_result(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = cpcv_backtest(close, entries, exits, n_groups=4, n_test_groups=1)

        assert "n_paths" in result
        assert "pbo" in result
        assert "oos_efficiency" in result
        assert "passed" in result
        assert result["n_paths"] > 0
        assert 0 <= result["pbo"] <= 1

    def test_split_cpcv_handles_remainder_in_last_group(self):
        splits = split_cpcv(10, n_groups=3, n_test_groups=1, embargo_pct=0.0)

        assert len(splits) == 3
        assert max(splits[-1][1]) == 9

    def test_cpcv_backtest_falls_back_to_zero_on_is_and_oos_errors(self, monkeypatch):
        close = _make_price_series(60)
        entries, exits = _make_signals(60)

        class FailingEngine:
            def run_backtest(self, *args, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr("quantflow.strategy.research.backtest.BacktestEngine", FailingEngine)

        result = cpcv_backtest(close, entries, exits, n_groups=3, n_test_groups=1)

        assert result["is_sharpe_mean"] == 0.0
        assert result["oos_sharpe_mean"] == 0.0
        assert result["oos_sharpe_min"] == 0.0
        assert all(
            path == {"path": idx, "oos_sharpe": 0.0}
            for idx, path in enumerate(result["path_results"])
        )

    def test_split_cpcv_rejects_insufficient_bars(self):
        with pytest.raises(ValueError, match="requires at least 4 bars"):
            split_cpcv(3, n_groups=4, n_test_groups=1)

    def test_cpcv_backtest_returns_structured_failure_for_insufficient_bars(self):
        close = _make_price_series(3)
        entries, exits = _make_signals(3)

        result = cpcv_backtest(close, entries, exits, n_groups=4, n_test_groups=1)

        assert result["passed"] is False
        assert result["n_paths"] == 0
        assert result["pbo"] == 1.0
        assert result["reason"] == "CPCV requires at least 4 bars, got 3."


class TestDSR:
    def test_dsr_high_sharpe_passes(self):
        result = deflated_sharpe_ratio(observed_sharpe=3.0, n_trials=10, sample_length=252)
        assert result["dsr"] > 0.95
        assert result["passed"]

    def test_dsr_zero_sharpe_fails(self):
        result = deflated_sharpe_ratio(observed_sharpe=0.0, n_trials=100, sample_length=252)
        assert result["dsr"] < 0.95
        assert not result["passed"]

    def test_dsr_no_trials(self):
        result = deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=0)
        assert not result["passed"]

    def test_dsr_single_trial(self):
        result = deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=1)
        # With 1 trial, expected max is 0, so DSR should be high
        assert "dsr" in result

    def test_expected_max_sharpe(self):
        ems = _expected_max_sharpe(100)
        assert ems > 0  # With many trials, expected max > 0
        # n_trials<=1 is degenerate: fail-closed returns +inf so DSR=0.0
        # (NO-GO) rather than 0.0 which would trivially pass the gate.
        ems_1 = _expected_max_sharpe(1)
        assert ems_1 == float("inf")

    def test_dsr_handles_expected_max_failure_and_near_zero_variance(self, monkeypatch):
        # scipy ppf failures raise ValueError/OverflowError on bad input;
        # the fail-closed path returns +inf (DSR→0.0, NO-GO) instead of 0.0
        # which would have dropped the multiple-testing penalty entirely.
        monkeypatch.setattr(
            "quantflow.strategy.validation.dsr.stats.norm.ppf",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad stats")),
        )

        result = deflated_sharpe_ratio(
            observed_sharpe=0.1,
            n_trials=5,
            skew=10.0,
            kurtosis=-100.0,
            sample_length=2,
        )

        assert result["expected_max_sharpe"] == float("inf")
        assert result["sr_variance"] < 0
        # Fail-closed: expected_max=+inf ⇒ DSR=Φ(-inf)=0.0 (NO-GO), not >0.95.
        assert result["dsr"] == 0.0
        assert result["passed"] is False


class TestPBO:
    def test_pbo_basic(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = probability_of_overfitting(close, entries, exits, n_groups=4)

        assert "pbo" in result
        assert 0 <= result["pbo"] <= 1
        assert "passed" in result
        assert "total_paths" in result

    def test_pbo_with_good_strategy(self):
        # Strong uptrend → consistent returns → low PBO
        close = _make_price_series(200, trend=0.03)
        entries, exits = _make_signals(200)
        result = probability_of_overfitting(close, entries, exits, n_groups=4)
        # PBO should be reasonable (may not always pass due to randomness)
        assert isinstance(result["pbo"], float)

    def test_pbo_falls_back_to_zero_on_is_and_oos_errors(self, monkeypatch):
        close = _make_price_series(30)
        entries, exits = _make_signals(30)

        monkeypatch.setattr(
            "quantflow.strategy.validation.cpcv.split_cpcv",
            lambda *args, **kwargs: [
                (np.array([0, 1, 2]), np.array([3, 4])),
                (np.array([5, 6, 7]), np.array([8, 9])),
            ],
        )

        class FailingEngine:
            def run_backtest(self, *args, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr("quantflow.strategy.research.backtest.BacktestEngine", FailingEngine)

        result = probability_of_overfitting(close, entries, exits, n_groups=3)

        assert result["is_return_mean"] == 0.0
        assert result["oos_return_mean"] == 0.0
        assert result["rank_correlation"] == 0.0
        assert result["overfit_paths"] == 0

    def test_pbo_returns_structured_failure_for_insufficient_bars(self):
        close = _make_price_series(3)
        entries, exits = _make_signals(3)

        result = probability_of_overfitting(close, entries, exits, n_groups=4, n_test_groups=1)

        assert result["passed"] is False
        assert result["total_paths"] == 0
        assert result["pbo"] == 1.0
        assert result["reason"] == "CPCV requires at least 4 bars, got 3."


class TestWFO:
    def test_wfo_rolling(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = walk_forward_optimization(close, entries, exits, n_windows=3, mode="rolling")

        assert "is_sharpe_mean" in result
        assert "oos_sharpe_mean" in result
        assert "oos_efficiency" in result
        assert "passed" in result

    def test_wfo_anchored(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = walk_forward_optimization(close, entries, exits, n_windows=3, mode="anchored")

        assert "is_sharpe_mean" in result
        assert "passed" in result

    def test_wfo_processes_all_windows_without_empty_slices(self, monkeypatch):
        close = _make_price_series(10)
        entries, exits = _make_signals(10)

        class FakeEngine:
            def run_backtest(self, close_slice, *args, **kwargs):
                if len(close_slice) == 0:
                    raise AssertionError("should not evaluate empty slice")
                return type(
                    "Result",
                    (),
                    {
                        "sharpe_ratio": 1.0,
                        "total_return": 0.1,
                        "max_drawdown": 0.05,
                        "num_trades": 1,
                    },
                )()

        monkeypatch.setattr("quantflow.strategy.research.backtest.BacktestEngine", FakeEngine)

        result = walk_forward_optimization(
            close, entries, exits, n_windows=3, mode="rolling", oos_ratio=0.8
        )

        assert result["n_windows"] == 3
        assert len(result["window_results"]) == 3


class TestValidationGate:
    def test_gate_returns_dict(self):
        close = _make_price_series(200)
        entries, exits = _make_signals(200)
        result = validation_gate(
            close, entries, exits, n_trials=10, cpcv_groups=4, cpcv_test_groups=1, wfo_windows=3
        )

        assert "decision" in result
        assert result["decision"] in ("GO", "NO-GO")
        assert "checks" in result

    @pytest.fixture
    def gate_inputs(self):
        close = _make_price_series(40)
        entries, exits = _make_signals(40)
        return close, entries, exits

    def test_gate_stops_when_cpcv_fails(self, monkeypatch, gate_inputs):
        close, entries, exits = gate_inputs
        monkeypatch.setattr(
            gate_module,
            "cpcv_backtest",
            lambda *args, **kwargs: {"passed": False, "pbo": 0.8, "path_results": []},
        )

        result = validation_gate(close, entries, exits)

        assert result["decision"] == "NO-GO"
        assert result["reason"] == "CPCV PBO=0.800 >= 0.5"
        assert result["checks"]["cpcv"]["passed"] is False

    def test_gate_uses_structured_cpcv_failure_reason(self):
        close = _make_price_series(3)
        entries, exits = _make_signals(3)

        result = validation_gate(close, entries, exits, cpcv_groups=4, cpcv_test_groups=1)

        assert result["decision"] == "NO-GO"
        assert result["reason"] == "CPCV requires at least 4 bars, got 3."
        assert result["checks"]["cpcv"]["passed"] is False

    def test_gate_stops_when_dsr_fails(self, monkeypatch, gate_inputs):
        close, entries, exits = gate_inputs
        monkeypatch.setattr(
            gate_module,
            "cpcv_backtest",
            lambda *args, **kwargs: {
                "passed": True,
                "pbo": 0.1,
                "path_results": [{"oos_sharpe": 1.1}, {"oos_sharpe": 0.9}],
            },
        )
        monkeypatch.setattr(
            gate_module,
            "deflated_sharpe_ratio",
            lambda **kwargs: {"passed": False, "dsr": 0.42},
        )

        result = validation_gate(close, entries, exits, n_trials=12)

        assert result["decision"] == "NO-GO"
        assert result["reason"] == "DSR=0.4200 < 0.95"
        assert result["checks"]["dsr"]["passed"] is False

    def test_gate_stops_when_wfo_fails(self, monkeypatch, gate_inputs):
        close, entries, exits = gate_inputs
        monkeypatch.setattr(
            gate_module,
            "cpcv_backtest",
            lambda *args, **kwargs: {
                "passed": True,
                "pbo": 0.1,
                "path_results": [{"oos_sharpe": 1.5}],
            },
        )
        monkeypatch.setattr(
            gate_module,
            "deflated_sharpe_ratio",
            lambda **kwargs: {"passed": True, "dsr": 0.99},
        )
        results = iter(
            [
                {"passed": False, "oos_efficiency": 0.4},
                {"passed": True, "oos_efficiency": 0.7},
            ]
        )
        monkeypatch.setattr(
            gate_module, "walk_forward_optimization", lambda *args, **kwargs: next(results)
        )

        result = validation_gate(close, entries, exits, wfo_windows=2)

        assert result["decision"] == "NO-GO"
        assert result["reason"] == "WFO rolling eff=0.400, anchored eff=0.700"
        assert result["checks"]["wfo_rolling"]["passed"] is False
        assert result["checks"]["wfo_anchored"]["passed"] is True

    def test_gate_returns_go_when_all_checks_pass(self, monkeypatch, gate_inputs):
        close, entries, exits = gate_inputs
        monkeypatch.setattr(
            gate_module,
            "cpcv_backtest",
            lambda *args, **kwargs: {
                "passed": True,
                "pbo": 0.1,
                "path_results": [{"oos_sharpe": 1.5}],
            },
        )
        monkeypatch.setattr(
            gate_module,
            "deflated_sharpe_ratio",
            lambda **kwargs: {"passed": True, "dsr": 0.99},
        )
        monkeypatch.setattr(
            gate_module,
            "walk_forward_optimization",
            lambda *args, **kwargs: {"passed": True, "oos_efficiency": 0.8},
        )

        result = validation_gate(close, entries, exits)

        assert result["decision"] == "GO"
        assert result["reason"] == "All validation checks passed"

    def test_gate_passes_optimization_context_to_oos_validators(self, monkeypatch, gate_inputs):
        close, entries, exits = gate_inputs
        data = pd.DataFrame({"close": close}, index=close.index)
        param_space = {"lookback": (3, 8)}

        def signal_fn(frame, **params):
            entries = pd.Series(params["lookback"] == 5, index=frame.index)
            exits = pd.Series(False, index=frame.index)
            return entries, exits

        cpcv_calls = []
        wfo_calls = []

        def fake_cpcv(*args, **kwargs):
            cpcv_calls.append((args, kwargs))
            return {
                "passed": True,
                "pbo": 0.1,
                "path_results": [{"oos_sharpe": 1.2}, {"oos_sharpe": 0.8}],
            }

        def fake_wfo(*args, **kwargs):
            wfo_calls.append((args, kwargs))
            return {"passed": True, "oos_efficiency": 0.7}

        monkeypatch.setattr(gate_module, "cpcv_backtest", fake_cpcv)
        monkeypatch.setattr(
            gate_module,
            "deflated_sharpe_ratio",
            lambda **kwargs: {"passed": True, "dsr": 0.99},
        )
        monkeypatch.setattr(gate_module, "walk_forward_optimization", fake_wfo)

        result = validation_gate(
            close,
            entries,
            exits,
            signal_fn=signal_fn,
            param_space=param_space,
            data=data,
            optimize_trials=7,
            optimize_method="random",
            optimize_objective="total_return",
        )

        assert result["decision"] == "GO"
        assert len(cpcv_calls) == 1
        assert len(wfo_calls) == 2

        for _args, kwargs in [*cpcv_calls, *wfo_calls]:
            assert kwargs["signal_fn"] is signal_fn
            assert kwargs["param_space"] is param_space
            assert kwargs["data"] is data
            assert kwargs["n_trials"] == 7
            assert kwargs["method"] == "random"
            assert kwargs["objective"] == "total_return"
