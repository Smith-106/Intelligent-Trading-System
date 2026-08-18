"""Benchmark service — orchestrates performance benchmarks across QuantFlow layers.

Replaces the ~400-line inline benchmark logic previously in cli/main.py.
The CLI benchmark command is now a thin shell that delegates to this service.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

from quantflow.common.config import AppConfig
from quantflow.common.models import Bar, Direction, OrderRequest, OrderSide
from quantflow.data.feature_store import FeatureStore
from quantflow.data.store import DataStore
from quantflow.execution.engine import ExecutionEngine
from quantflow.indicators.engine import IndicatorEngine
from quantflow.monitoring.sink import create_default_sink
from quantflow.strategy.base import StrategyBase, StrategyContext
from quantflow.strategy.engine import TradingSession
from quantflow.strategy.research.backtest import BacktestEngine
from quantflow.strategy.research.optimizer import StrategyOptimizer
from quantflow.strategy.templates.mean_reversion import MeanReversionStrategy
from quantflow.strategy.templates.trend_following import TrendFollowingStrategy
from quantflow.strategy.templates.volatility_breakout import VolatilityBreakoutStrategy
from quantflow.strategy.validation.wfo import walk_forward_optimization

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkRequest:
    """Parameters controlling benchmark execution."""

    bars: int = 500
    trials: int = 3
    wfo_windows: int = 2
    test_target: str = "tests/unit/test_cli.py"
    skip_subprocess: bool = False
    min_query_rows_per_sec: float | None = None
    min_bars_per_sec: float | None = None
    min_three_strategy_bars_per_sec: float | None = None
    min_orders_per_sec: float | None = None
    max_backtest_ms: float | None = None


@dataclass
class BenchmarkMetric:
    """A single benchmark measurement."""

    area: str
    metric: str
    value: float
    unit: str
    display: str


@dataclass
class BenchmarkFailure:
    """A threshold violation detected during benchmarking."""

    metric: str
    value: float
    operator: str
    threshold: float
    unit: str


@dataclass
class BenchmarkResult:
    """Aggregated benchmark results."""

    params: dict[str, Any]
    metrics: list[BenchmarkMetric]
    failures: list[BenchmarkFailure]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "params": self.params,
            "metrics": [
                {
                    "area": m.area,
                    "metric": m.metric,
                    "value": round(m.value, 6),
                    "unit": m.unit,
                }
                for m in self.metrics
            ],
            "failures": [
                {
                    "metric": f.metric,
                    "value": round(f.value, 6),
                    "operator": f.operator,
                    "threshold": f.threshold,
                    "unit": f.unit,
                }
                for f in self.failures
            ],
        }


# ---------------------------------------------------------------------------
# BenchmarkService
# ---------------------------------------------------------------------------


class BenchmarkService:
    """Orchestrate performance benchmarks across QuantFlow layers.

    Replaces the ~400-line inline benchmark logic previously in cli/main.py.
    """

    def run(self, request: BenchmarkRequest) -> BenchmarkResult:
        """Run all benchmarks and return aggregated result."""
        all_metrics: list[BenchmarkMetric] = []
        frame, close, entries, exits = self._create_synthetic_data(request.bars)

        all_metrics.extend(self._benchmark_data_layer(frame, request.bars))
        all_metrics.extend(self._benchmark_indicator_layer(frame))
        all_metrics.extend(self._benchmark_feature_layer(frame))
        all_metrics.extend(
            self._benchmark_research_layer(
                close, entries, exits, request.trials, request.wfo_windows
            )
        )
        all_metrics.extend(self._benchmark_runtime_layer(frame, close, request.bars))

        if not request.skip_subprocess:
            all_metrics.extend(self._benchmark_subprocess(request.test_target))

        failures = self._check_thresholds(all_metrics, request)

        return BenchmarkResult(
            params={
                "bars": request.bars,
                "trials": request.trials,
                "wfo_windows": request.wfo_windows,
                "test_target": request.test_target,
                "skip_subprocess": request.skip_subprocess,
            },
            metrics=all_metrics,
            failures=failures,
        )

    # ------------------------------------------------------------------
    # Helper methods (moved from inline closures in original benchmark)
    # ------------------------------------------------------------------

    @staticmethod
    def _metric_key(area: str, metric: str) -> str:
        normalized = metric.lower().replace(" ", "_").replace("/", "_per_")
        return f"{area}.{normalized}"

    def _time(
        self,
        area: str,
        metric: str,
        action: Callable[[], Any],
    ) -> tuple[Any, BenchmarkMetric]:
        """Execute *action*, measure elapsed ms, return (result, metric)."""
        started_at = perf_counter()
        value = action()
        elapsed_ms = (perf_counter() - started_at) * 1000
        return value, BenchmarkMetric(
            area=area,
            metric=metric,
            value=elapsed_ms,
            unit="ms",
            display=f"{elapsed_ms:.2f} ms",
        )

    @staticmethod
    def _throughput(
        area: str,
        metric: str,
        count: int,
        elapsed_ms: float,
    ) -> BenchmarkMetric:
        """Create a per-second throughput metric."""
        per_second = count / max(elapsed_ms / 1000, 1e-9)
        return BenchmarkMetric(
            area=area,
            metric=metric,
            value=per_second,
            unit="per_second",
            display=f"{per_second:.0f}/s",
        )

    # ------------------------------------------------------------------
    # Layer benchmarks
    # ------------------------------------------------------------------

    def _create_synthetic_data(
        self, bars: int
    ) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
        """Generate synthetic OHLCV data and entry/exit signals."""
        dates = pd.date_range("2024-01-01", periods=bars, freq="h", tz="UTC")
        rng = np.random.default_rng(42)
        close_values = 100.0 + np.cumsum(rng.normal(0.02, 0.8, bars))
        frame = pd.DataFrame(
            {
                "timestamp": [int(dt.timestamp() * 1000) for dt in dates],
                "datetime": dates,
                "open": close_values - 0.2,
                "high": close_values + 0.5,
                "low": close_values - 0.5,
                "close": close_values,
                "volume": rng.uniform(10.0, 100.0, bars),
                "symbol": "BTC/USDT",
                "timeframe": "1h",
            }
        )
        close = pd.Series(close_values, index=dates)
        rolling_mean = close.rolling(12, min_periods=1).mean()
        entries = (close > rolling_mean).fillna(False)
        exits = (close < rolling_mean).fillna(False)
        return frame, close, entries, exits

    def _benchmark_data_layer(self, frame: pd.DataFrame, bars: int) -> list[BenchmarkMetric]:
        """Benchmark DataStore save/query throughput."""
        metrics: list[BenchmarkMetric] = []
        with tempfile.TemporaryDirectory() as tmp:
            store = DataStore(str(Path(tmp) / "pq"), str(Path(tmp) / "db.duckdb"))
            _, m = self._time(
                "data", "save synthetic parquet", lambda: store.save(frame, "BTC/USDT")
            )
            metrics.append(m)

            started_at = perf_counter()
            queried = store.query(
                "BTC/USDT",
                start=int(frame["timestamp"].iloc[bars // 4]),
                end=int(frame["timestamp"].iloc[-1]),
                timeframe="1h",
                columns=("timestamp", "close", "volume"),
            )
            query_ms = (perf_counter() - started_at) * 1000
            metrics.append(
                BenchmarkMetric(
                    area="data",
                    metric="query projected range",
                    value=query_ms,
                    unit="ms",
                    display=f"{query_ms:.2f} ms",
                )
            )
            metrics.append(self._throughput("data", "query rows/sec", len(queried), query_ms))
            store.close()
        return metrics

    def _benchmark_indicator_layer(self, frame: pd.DataFrame) -> list[BenchmarkMetric]:
        """Benchmark IndicatorEngine batch/subset computation."""
        metrics: list[BenchmarkMetric] = []
        indicator_engine = IndicatorEngine()
        _, m = self._time(
            "indicators",
            "batch calculate all",
            lambda: indicator_engine.batch_calculate(frame),
        )
        metrics.append(m)
        _, m = self._time(
            "indicators",
            "compute requested subset",
            lambda: indicator_engine.compute_all(frame, ["rsi_14", "atr_14"]),
        )
        metrics.append(m)
        return metrics

    def _benchmark_feature_layer(self, frame: pd.DataFrame) -> list[BenchmarkMetric]:
        """Benchmark FeatureStore save/load throughput.

        ISS-002 fix: FeatureStore now requires ``indicator_computer`` injection.
        """
        metrics: list[BenchmarkMetric] = []
        indicator_engine = IndicatorEngine()
        with tempfile.TemporaryDirectory() as tmp:
            feature_store = FeatureStore(
                str(Path(tmp) / "features"),
                str(Path(tmp) / "features.duckdb"),
                indicator_computer=indicator_engine,
            )
            feature_frame = frame[["timestamp", "datetime", "close", "volume"]].copy()
            feature_frame["rsi_14"] = indicator_engine.compute_all(frame, ["rsi_14"])["rsi_14"]
            _, m = self._time(
                "feature_store",
                "save feature partitions",
                lambda: feature_store.save_features("BTC/USDT", feature_frame),
            )
            metrics.append(m)

            feature_start = int(frame["timestamp"].iloc[len(frame) // 4])
            feature_end = int(frame["timestamp"].iloc[-1])
            started_at = perf_counter()
            feature_rows = feature_store.load_features(
                "BTC/USDT",
                start=feature_start,
                end=feature_end,
            )
            feature_query_ms = (perf_counter() - started_at) * 1000
            metrics.append(
                BenchmarkMetric(
                    area="feature_store",
                    metric="load projected range",
                    value=feature_query_ms,
                    unit="ms",
                    display=f"{feature_query_ms:.2f} ms",
                )
            )
            metrics.append(
                self._throughput(
                    "feature_store", "load rows/sec", len(feature_rows), feature_query_ms
                )
            )
            feature_store.close()
        return metrics

    def _benchmark_research_layer(
        self,
        close: pd.Series,
        entries: pd.Series,
        exits: pd.Series,
        trials: int,
        wfo_windows: int,
    ) -> list[BenchmarkMetric]:
        """Benchmark BacktestEngine, StrategyOptimizer, and WFO."""
        metrics: list[BenchmarkMetric] = []
        engine = BacktestEngine()
        _, m = self._time(
            "research", "backtest", lambda: engine.run_backtest(close, entries, exits)
        )
        metrics.append(m)

        def _signal_fn(
            close_series: pd.Series, threshold: float = 1.0
        ) -> tuple[pd.Series, pd.Series]:
            mean = close_series.rolling(12, min_periods=1).mean()
            return close_series > mean * threshold, close_series < mean * threshold

        optimizer = StrategyOptimizer(engine=engine)
        _, m = self._time(
            "research",
            f"optimizer {trials} trials",
            lambda: optimizer.optimize(
                close,
                _signal_fn,
                {"threshold": (0.98, 1.02)},
                n_trials=trials,
                method="grid",
            ),
        )
        metrics.append(m)
        _, m = self._time(
            "validation",
            "optimized WFO",
            lambda: walk_forward_optimization(
                close,
                entries,
                exits,
                n_windows=wfo_windows,
                signal_fn=lambda data, threshold=1.0: _signal_fn(data["close"], threshold),
                param_space={"threshold": (0.98, 1.02)},
                data=pd.DataFrame({"close": close}, index=close.index),
                n_trials=trials,
                method="grid",
            ),
        )
        metrics.append(m)
        return metrics

    def _benchmark_runtime_layer(
        self, frame: pd.DataFrame, close: pd.Series, bars: int
    ) -> list[BenchmarkMetric]:
        """Benchmark TradingSession and ExecutionEngine throughput."""

        class NoSignalStrategy(StrategyBase):
            def __init__(self) -> None:
                super().__init__(name="benchmark_no_signal")

            def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
                if bar.close < 0:  # pragma: no cover — synthetic frame prices are always positive
                    ctx.emit_signal(bar.symbol, Direction.LONG, 1.0, bar.close, self.name)  # pragma: no cover

            def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:  # pragma: no cover — not invoked by the runtime benchmark
                empty = pd.Series(False, index=df.index)
                return empty, empty

        metrics: list[BenchmarkMetric] = []

        async def _runtime_baselines() -> None:
            def _bar_from_row(row: Any) -> Bar:
                return Bar(
                    symbol="BTC/USDT",
                    timestamp=int(row.timestamp),
                    open=float(row.open),
                    high=float(row.high),
                    low=float(row.low),
                    close=float(row.close),
                    volume=float(row.volume),
                )

            strategy = NoSignalStrategy()
            session = TradingSession(AppConfig(), [strategy], monitoring_sink=create_default_sink())
            await session.start(mode="paper")
            try:
                bar_slice = frame.tail(min(bars, 200))
                started = perf_counter()
                for row in bar_slice.itertuples(index=False):
                    await session.on_bar(_bar_from_row(row))
                elapsed_ms = (perf_counter() - started) * 1000
                metrics.append(
                    BenchmarkMetric(
                        area="runtime",
                        metric="TradingSession.on_bar batch",
                        value=elapsed_ms,
                        unit="ms",
                        display=f"{elapsed_ms:.2f} ms",
                    )
                )
                metrics.append(self._throughput("runtime", "bars/sec", len(bar_slice), elapsed_ms))
            finally:
                await session.stop()

            hot_path_bars = max(bars, 2000)
            hot_rng = np.random.default_rng(142)
            hot_dates = pd.date_range("2024-06-01", periods=hot_path_bars, freq="min", tz="UTC")
            hot_close = 100.0 + np.cumsum(hot_rng.normal(0.01, 0.6, hot_path_bars))
            hot_frame = pd.DataFrame(
                {
                    "timestamp": [int(dt.timestamp() * 1000) for dt in hot_dates],
                    "open": hot_close - 0.2,
                    "high": hot_close + 0.5,
                    "low": hot_close - 0.5,
                    "close": hot_close,
                    "volume": hot_rng.uniform(10.0, 100.0, hot_path_bars),
                }
            )
            hot_strategies = [
                TrendFollowingStrategy(),
                MeanReversionStrategy(),
                VolatilityBreakoutStrategy(),
            ]
            hot_contexts = [StrategyContext() for _ in hot_strategies]
            for hot_strategy, hot_context in zip(hot_strategies, hot_contexts, strict=True):
                hot_strategy.on_init(hot_context)

            started = perf_counter()
            for row in hot_frame.itertuples(index=False):
                hot_bar = _bar_from_row(row)
                for hot_strategy, hot_context in zip(hot_strategies, hot_contexts, strict=True):
                    hot_strategy.on_bar(hot_context, hot_bar)
                    hot_context.flush_signals()
            elapsed_ms = (perf_counter() - started) * 1000
            metrics.append(
                BenchmarkMetric(
                    area="runtime",
                    metric="three strategy on_bar batch",
                    value=elapsed_ms,
                    unit="ms",
                    display=f"{elapsed_ms:.2f} ms",
                )
            )
            metrics.append(
                self._throughput("runtime", "three strategy bars/sec", len(hot_frame), elapsed_ms)
            )

            execution = ExecutionEngine(monitoring_sink=create_default_sink())
            await execution.start(mode="paper")
            try:
                started = perf_counter()
                for _ in range(25):
                    await execution.submit_order(
                        OrderRequest(
                            symbol="BTC/USDT",
                            side=OrderSide.BUY,
                            order_type="market",
                            quantity=0.001,
                            price=float(close.iloc[-1]),
                            strategy_id="benchmark",
                        )
                    )
                elapsed_ms = (perf_counter() - started) * 1000
                metrics.append(
                    BenchmarkMetric(
                        area="execution",
                        metric="paper submit_order batch",
                        value=elapsed_ms,
                        unit="ms",
                        display=f"{elapsed_ms:.2f} ms",
                    )
                )
                metrics.append(self._throughput("execution", "orders/sec", 25, elapsed_ms))
            finally:
                await execution.stop()

        asyncio.run(_runtime_baselines())
        return metrics

    def _benchmark_subprocess(self, test_target: str) -> list[BenchmarkMetric]:
        """Benchmark CLI startup and pytest subprocess baselines."""
        metrics: list[BenchmarkMetric] = []
        _, m = self._time(
            "cli",
            "startup --help",
            lambda: subprocess.run(
                [sys.executable, "-m", "quantflow.cli.main", "--help"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            ),
        )
        metrics.append(m)
        _, m = self._time(
            "test",
            f"pytest {test_target}",
            lambda: subprocess.run(
                [sys.executable, "-m", "pytest", test_target, "-q"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            ),
        )
        metrics.append(m)
        return metrics

    def _check_thresholds(
        self, metrics: list[BenchmarkMetric], request: BenchmarkRequest
    ) -> list[BenchmarkFailure]:
        """Compare metrics against user-supplied thresholds."""
        metric_values: dict[str, float] = {}
        for m in metrics:
            key = self._metric_key(m.area, m.metric)
            metric_values[key] = m.value

        threshold_checks = [
            (
                "data.query_rows_per_sec",
                metric_values.get("data.query_rows_per_sec"),
                request.min_query_rows_per_sec,
                ">=",
                "per_second",
            ),
            (
                "runtime.bars_per_sec",
                metric_values.get("runtime.bars_per_sec"),
                request.min_bars_per_sec,
                ">=",
                "per_second",
            ),
            (
                "runtime.three_strategy_bars_per_sec",
                metric_values.get("runtime.three_strategy_bars_per_sec"),
                request.min_three_strategy_bars_per_sec,
                ">=",
                "per_second",
            ),
            (
                "execution.orders_per_sec",
                metric_values.get("execution.orders_per_sec"),
                request.min_orders_per_sec,
                ">=",
                "per_second",
            ),
            (
                "research.backtest",
                metric_values.get("research.backtest"),
                request.max_backtest_ms,
                "<=",
                "ms",
            ),
        ]
        failures: list[BenchmarkFailure] = []
        for key, value, threshold, operator, unit in threshold_checks:
            if threshold is None or value is None:
                continue
            failed = value < threshold if operator == ">=" else value > threshold
            if failed:
                failures.append(
                    BenchmarkFailure(
                        metric=key,
                        value=value,
                        operator=operator,
                        threshold=threshold,
                        unit=unit,
                    )
                )
        return failures
