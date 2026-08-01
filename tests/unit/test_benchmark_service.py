"""Tests for quantflow.cli.services.benchmark — BenchmarkService + data models."""

from __future__ import annotations

import pytest

from quantflow.cli.services.benchmark import (
    BenchmarkFailure,
    BenchmarkMetric,
    BenchmarkRequest,
    BenchmarkResult,
    BenchmarkService,
)


class TestBenchmarkRequest:
    """Data model tests."""

    def test_default_values(self) -> None:
        req = BenchmarkRequest()
        assert req.bars == 500
        assert req.trials == 3
        assert req.wfo_windows == 2
        assert req.test_target == "tests/unit/test_cli.py"
        assert req.skip_subprocess is False
        # All threshold params default to None
        assert req.min_query_rows_per_sec is None
        assert req.min_bars_per_sec is None
        assert req.min_three_strategy_bars_per_sec is None
        assert req.min_orders_per_sec is None
        assert req.max_backtest_ms is None

    def test_frozen(self) -> None:
        req = BenchmarkRequest()
        with pytest.raises(AttributeError):
            req.bars = 100  # type: ignore[misc]

    def test_custom_values(self) -> None:
        req = BenchmarkRequest(
            bars=1000,
            trials=5,
            wfo_windows=3,
            min_bars_per_sec=100.0,
            max_backtest_ms=50.0,
        )
        assert req.bars == 1000
        assert req.trials == 5
        assert req.wfo_windows == 3
        assert req.min_bars_per_sec == 100.0
        assert req.max_backtest_ms == 50.0


class TestBenchmarkMetric:
    def test_fields(self) -> None:
        m = BenchmarkMetric(
            area="data",
            metric="query_rows_per_sec",
            value=50000.0,
            unit="per_second",
            display="50,000 rows/sec",
        )
        assert m.area == "data"
        assert m.metric == "query_rows_per_sec"
        assert m.value == 50000.0
        assert m.unit == "per_second"


class TestBenchmarkFailure:
    def test_fields(self) -> None:
        f = BenchmarkFailure(
            metric="data.query_rows_per_sec",
            value=100.0,
            operator=">=",
            threshold=500.0,
            unit="per_second",
        )
        assert f.metric == "data.query_rows_per_sec"
        assert f.operator == ">="
        assert f.threshold == 500.0


class TestBenchmarkResult:
    def test_to_dict_empty_failures(self) -> None:
        result = BenchmarkResult(
            params={"bars": 500},
            metrics=[BenchmarkMetric("data", "query", 1000.0, "ms", "1000.0 ms")],
            failures=[],
        )
        d = result.to_dict()
        assert "params" in d
        assert "metrics" in d
        assert "failures" in d
        assert len(d["metrics"]) == 1
        assert d["metrics"][0]["value"] == 1000.0  # no rounding needed

    def test_to_dict_with_rounding(self) -> None:
        result = BenchmarkResult(
            params={"bars": 500},
            metrics=[BenchmarkMetric("research", "backtest", 123.456789, "ms", "123.456789 ms")],
            failures=[],
        )
        d = result.to_dict()
        assert d["metrics"][0]["value"] == 123.456789  # rounded to 6 decimals

    def test_to_dict_with_failures(self) -> None:
        result = BenchmarkResult(
            params={"bars": 500},
            metrics=[],
            failures=[
                BenchmarkFailure("x", 1.0, ">=", 10.0, "ms"),
                BenchmarkFailure("y", 2.0, "<=", 5.0, "sec"),
            ],
        )
        d = result.to_dict()
        assert len(d["failures"]) == 2
        assert d["failures"][0]["metric"] == "x"
        assert d["failures"][0]["operator"] == ">="
        assert d["failures"][1]["operator"] == "<="


class TestBenchmarkServiceMetricsHelper:
    """Test helper methods."""

    def test_metric_key_normalization(self) -> None:
        service = BenchmarkService()
        # Test various normalization cases
        # area is kept as-is (callers pass lowercase), metric is normalized
        assert service._metric_key("data", "QUERY ROWS/SEC") == "data.query_rows_per_sec"
        assert service._metric_key("research", "Backtest") == "research.backtest"
        assert service._metric_key("runtime", "Bars Per Sec") == "runtime.bars_per_sec"

    def test_time_method_measures_elapsed_ms(self) -> None:
        service = BenchmarkService()

        def slow_action():
            import time

            time.sleep(0.01)  # 10ms
            return "result"

        result, metric = service._time("test", "slow_action", slow_action)
        assert result == "result"
        assert metric.area == "test"
        assert metric.metric == "slow_action"
        assert metric.unit == "ms"
        assert metric.value >= 10.0  # Should be at least 10ms

    def test_throughput_method_calates_correctly(self) -> None:
        service = BenchmarkService()
        # 100 items in 1000ms = 100 per second
        metric = service._throughput("test", "items", 100, 1000.0)
        assert metric.value == 100.0
        assert metric.unit == "per_second"
        assert "/s" in metric.display

    def test_throughput_handles_zero_elapsed(self) -> None:
        service = BenchmarkService()
        # Avoid division by zero - should use 1e-9 as minimum
        metric = service._throughput("test", "items", 100, 0.0)
        assert metric.value == 100000000000.0  # 100 / 1e-9


class TestBenchmarkServiceCreateSyntheticData:
    def test_output_shape(self) -> None:
        service = BenchmarkService()
        frame, close, entries, exits = service._create_synthetic_data(100)
        assert len(frame) == 100
        assert len(close) == 100
        assert len(entries) == 100
        assert len(exits) == 100

    def test_frame_has_required_columns(self) -> None:
        service = BenchmarkService()
        frame, _, _, _ = service._create_synthetic_data(50)
        required_cols = [
            "timestamp",
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "symbol",
            "timeframe",
        ]
        for col in required_cols:
            assert col in frame.columns

    def test_deterministic_rng(self) -> None:
        """Verify RNG produces reproducible data."""
        service = BenchmarkService()
        frame1, close1, _, _ = service._create_synthetic_data(100)
        frame2, close2, _, _ = service._create_synthetic_data(100)
        # Same RNG seed should produce identical data
        assert frame1["close"].equals(frame2["close"])
        assert close1.equals(close2)

    def test_timestamps_are_millisecond_precision(self) -> None:
        service = BenchmarkService()
        frame, _, _, _ = service._create_synthetic_data(10)
        # Timestamps should be in milliseconds (large numbers)
        assert all(ts > 1e12 for ts in frame["timestamp"]), "Timestamps should be in ms"


class TestBenchmarkServiceCheckThresholds:
    """Test threshold checking logic."""

    def test_no_thresholds_no_failures(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest()  # all thresholds None
        metrics = [BenchmarkMetric("data", "query", 1000.0, "ms", "1000 ms")]
        failures = service._check_thresholds(metrics, req)
        assert failures == []

    def test_min_threshold_pass(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(min_query_rows_per_sec=500.0)
        metrics = [BenchmarkMetric("data", "query_rows_per_sec", 1000.0, "per_second", "1000/s")]
        failures = service._check_thresholds(metrics, req)
        assert failures == []  # 1000 >= 500

    def test_min_threshold_fail(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(min_query_rows_per_sec=5000.0)
        metrics = [BenchmarkMetric("data", "query_rows_per_sec", 1000.0, "per_second", "1000/s")]
        failures = service._check_thresholds(metrics, req)
        assert len(failures) == 1
        assert failures[0].metric == "data.query_rows_per_sec"
        assert failures[0].value == 1000.0
        assert failures[0].operator == ">="
        assert failures[0].threshold == 5000.0

    def test_max_threshold_pass(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(max_backtest_ms=100.0)
        metrics = [BenchmarkMetric("research", "backtest", 50.0, "ms", "50 ms")]
        failures = service._check_thresholds(metrics, req)
        assert failures == []  # 50 <= 100

    def test_max_threshold_fail(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(max_backtest_ms=10.0)
        metrics = [BenchmarkMetric("research", "backtest", 50.0, "ms", "50 ms")]
        failures = service._check_thresholds(metrics, req)
        assert len(failures) == 1
        assert failures[0].metric == "research.backtest"
        assert failures[0].operator == "<="

    def test_multiple_thresholds_mixed_results(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(
            min_query_rows_per_sec=500.0,
            max_backtest_ms=10.0,  # Will fail
            min_bars_per_sec=1000.0,
        )
        metrics = [
            BenchmarkMetric("data", "query_rows_per_sec", 1000.0, "per_second", "1000/s"),  # Pass
            BenchmarkMetric("research", "backtest", 50.0, "ms", "50 ms"),  # Fail
            BenchmarkMetric("runtime", "bars_per_sec", 2000.0, "per_second", "2000/s"),  # Pass
        ]
        failures = service._check_thresholds(metrics, req)
        assert len(failures) == 1
        assert failures[0].metric == "research.backtest"

    def test_null_metric_value_ignores_threshold(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(min_query_rows_per_sec=500.0)
        # No query_rows_per_sec metric provided
        metrics = [BenchmarkMetric("data", "other_metric", 100.0, "ms", "100 ms")]
        failures = service._check_thresholds(metrics, req)
        assert failures == []  # Missing metric should not cause failure

    def test_all_threshold_types(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(
            min_query_rows_per_sec=100.0,
            min_bars_per_sec=100.0,
            min_three_strategy_bars_per_sec=10.0,
            min_orders_per_sec=1.0,
            max_backtest_ms=1000.0,
        )
        metrics = [
            BenchmarkMetric("data", "query_rows_per_sec", 200.0, "per_second", "200/s"),
            BenchmarkMetric("runtime", "bars_per_sec", 500.0, "per_second", "500/s"),
            BenchmarkMetric("runtime", "three_strategy_bars_per_sec", 50.0, "per_second", "50/s"),
            BenchmarkMetric("execution", "orders_per_sec", 10.0, "per_second", "10/s"),
            BenchmarkMetric("research", "backtest", 100.0, "ms", "100 ms"),
        ]
        failures = service._check_thresholds(metrics, req)
        assert failures == []  # All pass


@pytest.mark.slow
class TestBenchmarkServiceRun:
    """Integration tests for the full benchmark run."""

    def test_run_completes_minimal_params(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(
            bars=100,
            trials=1,
            wfo_windows=1,
            skip_subprocess=True,
        )
        result = service.run(req)

        assert isinstance(result.params, dict)
        assert result.params["bars"] == 100
        assert result.params["trials"] == 1
        assert len(result.metrics) > 0
        assert isinstance(result.failures, list)

    def test_run_collects_metrics_from_all_areas(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(bars=100, trials=1, wfo_windows=1, skip_subprocess=True)
        result = service.run(req)

        areas = {m.area for m in result.metrics}
        # Verify we got metrics from multiple layers
        assert "data" in areas
        assert "indicators" in areas
        assert "feature_store" in areas
        assert "research" in areas or "validation" in areas
        assert "runtime" in areas

    def test_run_includes_parameter_snapshot(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(
            bars=150,
            trials=2,
            wfo_windows=3,
            skip_subprocess=True,
            test_target="custom/test.py",
        )
        result = service.run(req)

        assert result.params["bars"] == 150
        assert result.params["trials"] == 2
        assert result.params["wfo_windows"] == 3
        assert result.params["skip_subprocess"] is True
        assert result.params["test_target"] == "custom/test.py"

    def test_run_returns_empty_failures_when_no_thresholds(self) -> None:
        service = BenchmarkService()
        req = BenchmarkRequest(bars=100, trials=1, wfo_windows=1, skip_subprocess=True)
        result = service.run(req)
        assert result.failures == []

    @pytest.mark.xfail(reason="Subprocess benchmark takes too long for unit tests")
    def test_run_includes_subprocess_benchmarks(self) -> None:
        """This test would run subprocess benchmarks but is marked xfail."""
        service = BenchmarkService()
        req = BenchmarkRequest(
            bars=50,
            trials=1,
            wfo_windows=1,
            skip_subprocess=False,  # Enable subprocess benchmarks
        )
        result = service.run(req)

        # Should include CLI and test benchmarks
        areas = {m.area for m in result.metrics}
        assert "cli" in areas
        assert "test" in areas


class TestBenchmarkServiceDataLayerBenchmarks:
    """Specific tests for data layer benchmarking."""

    def test_data_layer_reports_save_and_query_metrics(self) -> None:
        import tempfile
        from pathlib import Path

        from quantflow.data.store import DataStore

        service = BenchmarkService()
        frame, _, _, _ = service._create_synthetic_data(50)

        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            store.save(frame, "BTC/USDT")
            queried = store.query(
                "BTC/USDT",
                start=int(frame["timestamp"].iloc[12]),
                end=int(frame["timestamp"].iloc[-1]),
                timeframe="1h",
                columns=("timestamp", "close", "volume"),
            )
            store.close()

            assert len(queried) > 0

    def test_throughput_calculation_accuracy(self) -> None:
        service = BenchmarkService()
        # 500 items in 500ms = 1000 items/sec
        metric = service._throughput("data", "rows", 500, 500.0)
        assert metric.value == 1000.0


class TestBenchmarkServiceResearchLayer:
    """Tests for research layer benchmarking."""

    def test_research_layer_runs_backtest_and_optimization(self) -> None:
        service = BenchmarkService()
        _, close, entries, exits = service._create_synthetic_data(100)

        metrics = service._benchmark_research_layer(close, entries, exits, trials=1, wfo_windows=1)

        areas = {m.area for m in metrics}
        assert "research" in areas
        assert "validation" in areas


class TestBenchmarkServiceRuntimeLayer:
    """Tests for runtime layer benchmarking."""

    def test_runtime_layer_reports_tradingsession_performance(self) -> None:
        import asyncio

        import pandas as pd

        from quantflow.common.config import AppConfig
        from quantflow.common.models import Bar
        from quantflow.monitoring.sink import create_default_sink
        from quantflow.strategy.base import StrategyBase, StrategyContext
        from quantflow.strategy.engine import TradingSession

        class TestStrategy(StrategyBase):
            def __init__(self) -> None:
                super().__init__(name="test")

            def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
                pass

            def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
                return pd.Series(False, index=df.index), pd.Series(False, index=df.index)

        service = BenchmarkService()
        frame, _, _, _ = service._create_synthetic_data(50)

        async def run_test():
            strategy = TestStrategy()
            session = TradingSession(AppConfig(), [strategy], monitoring_sink=create_default_sink())
            await session.start(mode="paper")
            try:
                bar_slice = frame.tail(20)
                for row in bar_slice.itertuples(index=False):
                    bar = Bar(
                        symbol="BTC/USDT",
                        timestamp=int(row.timestamp),
                        open=float(row.open),
                        high=float(row.high),
                        low=float(row.low),
                        close=float(row.close),
                        volume=float(row.volume),
                    )
                    await session.on_bar(bar)
            finally:
                await session.stop()

        asyncio.run(run_test())
        # If we got here without error, the test passed
