"""Comprehensive tests for web/service.py — helper functions and StationService methods."""

from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.research.backtest import BacktestResult


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestDemoFreqForTimeframe:
    def test_known_timeframes(self):
        from quantflow.web.service import _demo_freq_for_timeframe
        assert _demo_freq_for_timeframe("1m") == "1min"
        assert _demo_freq_for_timeframe("5m") == "5min"
        assert _demo_freq_for_timeframe("15m") == "15min"
        assert _demo_freq_for_timeframe("1h") == "1h"
        assert _demo_freq_for_timeframe("4h") == "4h"
        assert _demo_freq_for_timeframe("1d") == "1D"

    def test_unknown_defaults_to_4h(self):
        from quantflow.web.service import _demo_freq_for_timeframe
        assert _demo_freq_for_timeframe("2h") == "4h"
        assert _demo_freq_for_timeframe("1w") == "4h"


class TestDockerAvailable:
    def test_docker_available_true(self):
        from quantflow.web.service import _docker_available
        with patch("quantflow.web.service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert _docker_available() is True

    def test_docker_available_false(self):
        from quantflow.web.service import _docker_available
        with patch("quantflow.web.service.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert _docker_available() is False

    def test_docker_exception(self):
        from quantflow.web.service import _docker_available
        with patch("quantflow.web.service.subprocess.run", side_effect=Exception):
            assert _docker_available() is False


class TestPortReachable:
    def test_port_reachable_true(self):
        from quantflow.web.service import _port_reachable
        with patch("quantflow.web.service.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock(return_value=None)
            mock_conn.return_value.__exit__ = MagicMock(return_value=None)
            assert _port_reachable("127.0.0.1", 9090) is True

    def test_port_reachable_false(self):
        from quantflow.web.service import _port_reachable
        with patch("quantflow.web.service.socket.create_connection", side_effect=OSError):
            assert _port_reachable("127.0.0.1", 9090) is False


class TestTimestampToIso:
    def test_valid_timestamp(self):
        from quantflow.web.service import _timestamp_to_iso
        # 1700000000000 ms = 2023-11-14...
        result = _timestamp_to_iso(1700000000000)
        assert result is not None
        assert "2023" in result

    def test_none_input(self):
        from quantflow.web.service import _timestamp_to_iso
        assert _timestamp_to_iso(None) is None

    def test_invalid_input(self):
        from quantflow.web.service import _timestamp_to_iso
        assert _timestamp_to_iso("not_a_number") is None


class TestSeriesPayload:
    def test_short_series(self):
        from quantflow.web.service import _series_payload
        s = pd.Series([1.0, 2.0, 3.0], index=[10, 20, 30])
        payload = _series_payload(s)
        assert payload["labels"] == ["10", "20", "30"]
        assert len(payload["values"]) == 3

    def test_long_series_downsampled(self):
        from quantflow.web.service import _series_payload
        s = pd.Series(range(500), index=range(500))
        payload = _series_payload(s, max_points=100)
        assert len(payload["labels"]) <= 101  # includes last point


class TestLabelForIndex:
    def test_timestamp_index(self):
        from quantflow.web.service import _label_for_index
        ts = pd.Timestamp("2024-01-01", tz="UTC")
        result = _label_for_index(ts)
        assert "2024" in result

    def test_non_timestamp(self):
        from quantflow.web.service import _label_for_index
        assert _label_for_index(42) == "42"


class TestNumericSeries:
    def test_existing_column(self):
        from quantflow.web.service import _numeric_series
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
        result = _numeric_series(df, "close", pd.Series([0.0, 0.0, 0.0]))
        assert list(result) == [100.0, 101.0, 102.0]

    def test_missing_column_uses_fallback(self):
        from quantflow.web.service import _numeric_series
        df = pd.DataFrame({"open": [100.0]})
        fallback = pd.Series([50.0])
        result = _numeric_series(df, "close", fallback)
        assert result.iloc[0] == 50.0

    def test_nan_filled_with_fallback(self):
        from quantflow.web.service import _numeric_series
        df = pd.DataFrame({"close": [100.0, None, 102.0]})
        fallback = pd.Series([0.0, 0.0, 0.0])
        result = _numeric_series(df, "close", fallback)
        assert result.iloc[1] == 0.0


class TestChartPositions:
    def test_short_series(self):
        from quantflow.web.service import _chart_positions
        result = _chart_positions(100)
        assert result == list(range(100))

    def test_long_series(self):
        from quantflow.web.service import _chart_positions
        result = _chart_positions(1000, max_points=100)
        assert len(result) <= 101
        assert 999 in result  # last element always included


class TestLineValues:
    def test_basic(self):
        from quantflow.web.service import _line_values
        s = pd.Series([1.0, 2.0, 3.0])
        positions = [0, 2]
        result = _line_values(s, positions)
        assert len(result) == 2
        assert result[0] == 1.0
        assert result[1] == 3.0

    def test_nan_becomes_none(self):
        from quantflow.web.service import _line_values
        s = pd.Series([1.0, float("nan"), 3.0])
        positions = [0, 1, 2]
        result = _line_values(s, positions)
        assert result[1] is None


class TestNearestChartIndex:
    def test_exact_match(self):
        from quantflow.web.service import _nearest_chart_index
        positions = [0, 10, 20, 30]
        assert _nearest_chart_index(10, positions) == 1

    def test_before_first(self):
        from quantflow.web.service import _nearest_chart_index
        positions = [5, 10, 20]
        assert _nearest_chart_index(3, positions) == 0

    def test_after_last(self):
        from quantflow.web.service import _nearest_chart_index
        positions = [5, 10, 20]
        assert _nearest_chart_index(25, positions) == 2


class TestMarkerPayload:
    def test_with_signals(self):
        from quantflow.web.service import _marker_payload
        signals = pd.Series([False, True, False, True])
        prices = pd.Series([100.0, 101.0, 102.0, 103.0])
        positions = [0, 1, 2, 3]
        markers = _marker_payload(signals, prices, positions, side="entry")
        assert len(markers) == 2
        assert markers[0]["side"] == "entry"

    def test_no_signals(self):
        from quantflow.web.service import _marker_payload
        signals = pd.Series([False, False, False])
        prices = pd.Series([100.0, 101.0, 102.0])
        positions = [0, 1, 2]
        markers = _marker_payload(signals, prices, positions, side="exit")
        assert len(markers) == 0


class TestNormalizeDataSource:
    def test_okx_variants(self):
        from quantflow.web.service import _normalize_data_source
        assert _normalize_data_source("okx") == "okx"
        assert _normalize_data_source("market") == "okx"
        assert _normalize_data_source("OKX") == "okx"
        assert _normalize_data_source("Market") == "okx"

    def test_demo_variants(self):
        from quantflow.web.service import _normalize_data_source
        assert _normalize_data_source("demo") == "demo"
        assert _normalize_data_source("Demo") == "demo"

    def test_none_returns_unknown(self):
        from quantflow.web.service import _normalize_data_source
        assert _normalize_data_source(None) == "unknown"

    def test_nan_returns_unknown(self):
        from quantflow.web.service import _normalize_data_source
        assert _normalize_data_source(float("nan")) == "unknown"

    def test_empty_string(self):
        from quantflow.web.service import _normalize_data_source
        assert _normalize_data_source("") == "unknown"
        assert _normalize_data_source("none") == "unknown"
        assert _normalize_data_source("null") == "unknown"

    def test_other_value_passes_through(self):
        from quantflow.web.service import _normalize_data_source
        assert _normalize_data_source("custom") == "custom"


class TestFrameSourceBreakdown:
    def test_empty_frame(self):
        from quantflow.web.service import _frame_source_breakdown
        df = pd.DataFrame()
        assert _frame_source_breakdown(df) == {}

    def test_no_data_source_column(self):
        from quantflow.web.service import _frame_source_breakdown
        df = pd.DataFrame({"close": [100.0]})
        assert _frame_source_breakdown(df) == {"unknown": 1}

    def test_with_data_source(self):
        from quantflow.web.service import _frame_source_breakdown
        df = pd.DataFrame({"data_source": ["okx", "okx", "demo"]})
        result = _frame_source_breakdown(df)
        assert result["okx"] == 2
        assert result["demo"] == 1


class TestResolveFrameDataSource:
    def test_single_source(self):
        from quantflow.web.service import _resolve_frame_data_source
        df = pd.DataFrame({"data_source": ["okx", "okx"]})
        source, breakdown = _resolve_frame_data_source(df)
        assert source == "okx"
        assert breakdown["okx"] == 2

    def test_empty_frame(self):
        from quantflow.web.service import _resolve_frame_data_source
        df = pd.DataFrame()
        source, breakdown = _resolve_frame_data_source(df)
        assert source == "unknown"

    def test_mixed_sources(self):
        from quantflow.web.service import _resolve_frame_data_source
        df = pd.DataFrame({"data_source": ["okx", "demo"]})
        source, breakdown = _resolve_frame_data_source(df)
        assert source == "hybrid"


class TestResolveDataMode:
    def test_no_symbols(self):
        from quantflow.web.service import _resolve_data_mode
        assert _resolve_data_mode({}, 0) == "demo-ready"

    def test_market_mode(self):
        from quantflow.web.service import _resolve_data_mode
        assert _resolve_data_mode({"okx": 3}, 3) == "market"

    def test_demo_seeded(self):
        from quantflow.web.service import _resolve_data_mode
        assert _resolve_data_mode({"demo": 2}, 2) == "demo-seeded"

    def test_source_unknown(self):
        from quantflow.web.service import _resolve_data_mode
        assert _resolve_data_mode({"unknown": 1}, 1) == "source-unknown"

    def test_hybrid(self):
        from quantflow.web.service import _resolve_data_mode
        assert _resolve_data_mode({"okx": 2, "demo": 1}, 3) == "hybrid"

    def test_no_active_sources(self):
        from quantflow.web.service import _resolve_data_mode
        assert _resolve_data_mode({"okx": 0}, 2) == "source-unknown"


class TestDataMemberContext:
    def test_market(self):
        from quantflow.web.service import _data_mode_context
        ctx = _data_mode_context("market")
        assert "title" in ctx
        assert "message" in ctx

    def test_unknown_mode(self):
        from quantflow.web.service import _data_mode_context
        ctx = _data_mode_context("nonexistent")
        assert ctx["title"] == "Unknown data mode"


class TestFormatDataSourceLabel:
    def test_okx(self):
        from quantflow.web.service import format_data_source_label
        assert format_data_source_label("okx") == "Market"

    def test_demo(self):
        from quantflow.web.service import format_data_source_label
        assert format_data_source_label("demo") == "Demo"

    def test_unknown(self):
        from quantflow.web.service import format_data_source_label
        assert format_data_source_label("unknown") == "Unknown"

    def test_hybrid(self):
        from quantflow.web.service import format_data_source_label
        assert format_data_source_label("hybrid") == "Hybrid"

    def test_custom(self):
        from quantflow.web.service import format_data_source_label
        assert format_data_source_label("custom_source") == "custom_source"


class TestBuildDemoFrame:
    def test_basic(self):
        from quantflow.web.service import _build_demo_frame
        df = _build_demo_frame("BTC/USDT")
        assert len(df) == 360
        assert "close" in df.columns
        assert "timestamp" in df.columns
        assert "symbol" in df.columns

    def test_with_start(self):
        from quantflow.web.service import _build_demo_frame
        df = _build_demo_frame("ETH/USDT", start="2024-01-01", end="2024-06-01")
        assert len(df) > 0

    def test_short_start_end_range(self):
        from quantflow.web.service import _build_demo_frame
        # Start and end close together → few candidate_index, backfill
        df = _build_demo_frame("BTC/USDT", start="2024-01-01", end="2024-01-02", bars=100)
        assert len(df) > 0

    def test_large_range_downsampled(self):
        from quantflow.web.service import _build_demo_frame
        # Very large start-end range → more candidate bars than `bars` → downsampled
        df = _build_demo_frame("BTC/USDT", start="2020-01-01", end="2026-01-01", bars=100, timeframe="1h")
        assert len(df) == 100

    def test_no_start(self):
        from quantflow.web.service import _build_demo_frame
        df = _build_demo_frame("BTC/USDT", bars=50)
        assert len(df) == 50


class TestToJsoonable:
    def test_dict(self):
        from quantflow.web.service import _to_jsonable
        result = _to_jsonable({"a": 1, "b": 2.0})
        assert result == {"a": 1, "b": 2.0}

    def test_list(self):
        from quantflow.web.service import _to_jsonable
        result = _to_jsonable([1, 2, 3])
        assert result == [1, 2, 3]

    def test_path(self):
        from quantflow.web.service import _to_jsonable
        result = _to_jsonable(Path("/tmp/test"))
        assert isinstance(result, str)

    def test_numpy_generic(self):
        from quantflow.web.service import _to_jsonable
        result = _to_jsonable(np.float64(3.14))
        assert isinstance(result, float)

    def test_pandas_series(self):
        from quantflow.web.service import _to_jsonable
        s = pd.Series([1.0, 2.0])
        result = _to_jsonable(s)
        assert isinstance(result, dict)
        assert "labels" in result

    def test_pandas_timestamp(self):
        from quantflow.web.service import _to_jsonable
        ts = pd.Timestamp("2024-01-01", tz="UTC")
        result = _to_jsonable(ts)
        assert isinstance(result, str)
        assert "2024" in result


class TestValidationTone:
    def test_nogo(self):
        from quantflow.web.service import _validation_tone
        assert _validation_tone(decision="NO-GO") == "danger"
        assert _validation_tone(decision="fail") == "danger"
        assert _validation_tone(decision="failed") == "danger"

    def test_go(self):
        from quantflow.web.service import _validation_tone
        assert _validation_tone(decision="GO") == "accent"
        assert _validation_tone(decision="pass") == "accent"
        assert _validation_tone(decision="passed") == "accent"

    def test_passed_flag(self):
        from quantflow.web.service import _validation_tone
        assert _validation_tone(passed=True) == "accent"
        assert _validation_tone(passed=False) == "danger"

    def test_muted_default(self):
        from quantflow.web.service import _validation_tone
        assert _validation_tone() == "muted"


class TestSummaryText:
    def test_with_value(self):
        from quantflow.web.service import _summary_text
        assert _summary_text("hello") == "hello"

    def test_none(self):
        from quantflow.web.service import _summary_text
        assert _summary_text(None) == "N/A"

    def test_empty_string(self):
        from quantflow.web.service import _summary_text
        assert _summary_text("") == "N/A"


class TestValidationMetric:
    def test_basic(self):
        from quantflow.web.service import _validation_metric
        m = _validation_metric("Sharpe", 1.5)
        assert m["label"] == "Sharpe"
        assert m["value"] == 1.5
        assert m["format"] == "number"

    def test_with_tone(self):
        from quantflow.web.service import _validation_metric
        m = _validation_metric("PBO", 0.75, tone="danger")
        assert m["tone"] == "danger"


class TestValidationSummary:
    def test_gate_method_passed(self):
        from quantflow.web.service import _validation_summary
        payload = {
            "method": "gate",
            "result": {"decision": "GO", "checks": {"cpcv": {"passed": True, "pbo": 0.3, "n_paths": 10, "oos_efficiency": 0.6, "oos_sharpe_mean": 1.2}}},
            "signals": {"entries": 5, "exits": 3, "bars": 100},
            "backtest": {},
        }
        summary = _validation_summary(payload)
        assert summary["method"] == "gate"
        assert summary["outcome_tone"] == "accent"

    def test_gate_method_failed(self):
        from quantflow.web.service import _validation_summary
        payload = {
            "method": "gate",
            "result": {"decision": "NO-GO", "checks": {"cpcv": {"passed": False, "pbo": 0.9}}},
            "signals": {"entries": 5, "exits": 3, "bars": 100},
            "backtest": {},
        }
        summary = _validation_summary(payload)
        assert summary["outcome_tone"] == "danger"

    def test_dsr_method(self):
        from quantflow.web.service import _validation_summary
        payload = {
            "method": "dsr",
            "result": {"passed": True, "dsr": 0.05, "observed_sharpe": 1.5, "expected_max_sharpe": 1.2, "n_trials": 50},
            "signals": {"entries": 5, "exits": 3, "bars": 100},
            "backtest": {"total_return": 0.15, "num_trades": 20, "max_drawdown": -0.05},
        }
        summary = _validation_summary(payload)
        assert summary["method"] == "dsr"
        assert summary["decision"] == "PASS"

    def test_pbo_method(self):
        from quantflow.web.service import _validation_summary
        payload = {
            "method": "pbo",
            "result": {"passed": False, "pbo": 0.8, "overfit_paths": 5, "total_paths": 10, "oos_return_mean": 0.01, "is_return_mean": 0.05, "rank_correlation": 0.3},
            "signals": {"entries": 5, "exits": 3, "bars": 100},
            "backtest": {},
        }
        summary = _validation_summary(payload)
        assert summary["method"] == "pbo"
        assert summary["decision"] == "FAIL"

    def test_cpcv_method(self):
        from quantflow.web.service import _validation_summary
        payload = {
            "method": "cpcv",
            "result": {"passed": True, "oos_sharpe_mean": 1.3, "pbo": 0.2, "oos_efficiency": 0.7, "n_paths": 15, "signal_quality": {"precision": 0.6, "recall": 0.5, "n_signals": 10}},
            "signals": {"entries": 5, "exits": 3, "bars": 100},
            "backtest": {},
        }
        summary = _validation_summary(payload)
        assert summary["method"] == "cpcv"
        assert summary["decision"] == "PASS"

    def test_wfo_method_both_pass(self):
        from quantflow.web.service import _validation_summary
        payload = {
            "method": "wfo",
            "result": {"rolling": {"passed": True, "oos_sharpe_mean": 1.1, "oos_efficiency": 0.6, "n_windows": 3, "decision": "PASS"}, "anchored": {"passed": True, "oos_sharpe_mean": 1.0, "oos_efficiency": 0.5, "decision": "PASS"}},
            "signals": {"entries": 5, "exits": 3, "bars": 100},
            "backtest": {},
        }
        summary = _validation_summary(payload)
        assert summary["method"] == "wfo"
        assert summary["decision"] == "PASS"

    def test_wfo_method_mixed(self):
        from quantflow.web.service import _validation_summary
        payload = {
            "method": "wfo",
            "result": {"rolling": {"passed": True, "decision": "PASS"}, "anchored": {"passed": False, "decision": "FAIL"}},
            "signals": {"entries": 5, "exits": 3, "bars": 100},
            "backtest": {},
        }
        summary = _validation_summary(payload)
        assert summary["decision"] == "MIXED"
        assert summary["outcome_tone"] == "warning"

    def test_wfo_method_both_fail(self):
        from quantflow.web.service import _validation_summary
        payload = {
            "method": "wfo",
            "result": {"rolling": {"passed": False, "oos_sharpe_mean": 0.2, "decision": "FAIL"}, "anchored": {"passed": False, "oos_sharpe_mean": 0.1, "decision": "FAIL"}},
            "signals": {"entries": 5, "exits": 3, "bars": 100},
            "backtest": {},
        }
        summary = _validation_summary(payload)
        assert summary["decision"] == "FAIL"

    def test_unknown_method(self):
        from quantflow.web.service import _validation_summary
        payload = {
            "method": "custom",
            "result": {},
            "signals": {"entries": 5, "exits": 3, "bars": 100},
            "backtest": {},
        }
        summary = _validation_summary(payload)
        assert summary["method"] == "custom"
        assert summary["decision"] == "N/A"


class TestResultPayload:
    def test_basic(self):
        from quantflow.web.service import _result_payload
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        close = pd.Series(100.0 + np.random.default_rng(42).normal(0, 1, 50).cumsum(), index=dates)
        result = BacktestResult(
            strategy_id="test",
            symbol="BTC/USDT",
            start_date="2024-01-01",
            end_date="2024-02-20",
            initial_capital=10000.0,
            final_capital=10500.0,
            total_return=0.05,
            annual_return=0.3,
            sharpe_ratio=1.5,
            sortino_ratio=2.0,
            calmar_ratio=1.8,
            max_drawdown=-0.05,
            win_rate=0.6,
            profit_factor=1.8,
            num_trades=10,
            equity_curve=pd.Series(10000.0 + np.arange(50) * 10, index=dates),
            drawdown_curve=pd.Series(0.0, index=dates),
        )
        payload = _result_payload(result)
        assert payload["strategy_id"] == "test"
        assert "equity_curve" in payload


class TestChartPayload:
    def test_basic(self):
        from quantflow.web.service import _chart_payload
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        frame = pd.DataFrame({
            "open": pd.Series(100.0, index=dates),
            "high": pd.Series(101.0, index=dates),
            "low": pd.Series(99.0, index=dates),
            "close": pd.Series(100.5, index=dates),
            "volume": pd.Series(1000.0, index=dates),
        })
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        result = BacktestResult(
            strategy_id="test",
            symbol="BTC/USDT",
            start_date="2024-01-01",
            end_date="2024-02-20",
            initial_capital=10000.0,
            final_capital=10500.0,
            total_return=0.05,
            annual_return=0.3,
            sharpe_ratio=1.5,
            sortino_ratio=2.0,
            calmar_ratio=1.8,
            max_drawdown=-0.05,
            win_rate=0.6,
            profit_factor=1.8,
            num_trades=10,
            equity_curve=pd.Series(10000.0 + np.arange(50) * 10, index=dates),
            drawdown_curve=pd.Series(0.0, index=dates),
        )
        payload = _chart_payload(frame, entries, exits, result)
        assert "candles" in payload
        assert "volume" in payload
        assert "secondary" in payload
        assert "markers" in payload
        assert "meta" in payload

    def test_with_timeframe_column(self):
        from quantflow.web.service import _chart_payload
        dates = pd.date_range("2024-01-01", periods=20, freq="D")
        frame = pd.DataFrame({
            "open": pd.Series(100.0, index=dates),
            "high": pd.Series(101.0, index=dates),
            "low": pd.Series(99.0, index=dates),
            "close": pd.Series(100.5, index=dates),
            "volume": pd.Series(1000.0, index=dates),
            "timeframe": pd.Series("4h", index=dates),
        })
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        result = BacktestResult(
            strategy_id="t", symbol="BTC/USDT", start_date="2024-01-01", end_date="2024-01-20",
            initial_capital=10000.0, final_capital=10500.0, total_return=0.05, annual_return=0.3,
            sharpe_ratio=1.5, sortino_ratio=2.0, calmar_ratio=1.8, max_drawdown=-0.05,
            win_rate=0.6, profit_factor=1.8, num_trades=5,
            equity_curve=pd.Series(10000.0, index=dates), drawdown_curve=pd.Series(0.0, index=dates),
        )
        payload = _chart_payload(frame, entries, exits, result)
        assert payload["timeframe"] == "4h"

    def test_with_entry_exit_markers(self):
        from quantflow.web.service import _chart_payload
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        frame = pd.DataFrame({
            "open": pd.Series(100.0, index=dates),
            "high": pd.Series(101.0, index=dates),
            "low": pd.Series(99.0, index=dates),
            "close": pd.Series(100.5, index=dates),
            "volume": pd.Series(1000.0, index=dates),
        })
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        entries.iloc[10] = True
        exits.iloc[20] = True
        result = BacktestResult(
            strategy_id="t", symbol="BTC/USDT", start_date="2024-01-01", end_date="2024-02-20",
            initial_capital=10000.0, final_capital=10500.0, total_return=0.05, annual_return=0.3,
            sharpe_ratio=1.5, sortino_ratio=2.0, calmar_ratio=1.8, max_drawdown=-0.05,
            win_rate=0.6, profit_factor=1.8, num_trades=5,
            equity_curve=pd.Series(10000.0 + np.arange(50) * 10, index=dates),
            drawdown_curve=pd.Series(0.0, index=dates),
        )
        payload = _chart_payload(frame, entries, exits, result)
        assert len(payload["markers"]["entries"]) > 0
        assert len(payload["markers"]["exits"]) > 0


# ---------------------------------------------------------------------------
# StationService methods
# ---------------------------------------------------------------------------


class TestStationServiceOverview:
    def test_overview_returns_dict(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test_parquet"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = True
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                result = service.overview()
                assert isinstance(result, dict)
                assert "version" in result
                assert "data" in result
                assert "strategies" in result
                mock_store.close.assert_called_once()


class TestStationServiceStrategies:
    def test_strategies_returns_list(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.list_strategy_summaries", return_value=[{"name": "test"}]):
            service = StationService(history_store=StationHistoryStore())
            result = service.strategies()
            assert isinstance(result, list)
            assert len(result) == 1


class TestStationServiceDataSnapshot:
    def test_data_snapshot_no_symbols(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/nonexistent"
            mock_config.data.duckdb_path = "/tmp/nonexistent.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                result = service.data_snapshot()
                assert isinstance(result, dict)
                assert "highlights" in result
                assert result["summary"]["symbol_count"] == 0

    def test_data_snapshot_with_symbols(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/nonexistent"
            mock_config.data.duckdb_path = "/tmp/nonexistent.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = ["BTC_USDT"]
            query_frame = pd.DataFrame({
                "timestamp": [1700000000000],
                "data_source": ["okx"],
            })
            mock_store.query.return_value = query_frame
            mock_store.get_date_range.return_value = (1700000000000, 1700003600000)
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store), \
                 patch("quantflow.web.service._resolve_frame_data_source", return_value=("okx", {"okx": 1})):
                service = StationService(history_store=StationHistoryStore())
                result = service.data_snapshot()
                assert result["summary"]["symbol_count"] >= 1
                assert len(result["highlights"]) > 0


class TestStationServiceSeedDemo:
    def test_seed_demo_data(self):
        from quantflow.web.service import StationService, DataDownloadRequest
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load:
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test_parquet"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.save = MagicMock()
            mock_store.get_date_range.return_value = (1700000000000, 1700003600000)
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                request = DataDownloadRequest(symbol="BTC/USDT", config_path="test.yaml")
                result = service.seed_demo_data(request)
                assert result["data_source"] == "demo"
                assert result["rows_saved"] > 0
                mock_store.save.assert_called_once()

    def test_seed_demo_invalid_range(self):
        from quantflow.web.service import StationService, DataDownloadRequest
        from quantflow.web.history import StationHistoryStore
        service = StationService(history_store=StationHistoryStore())
        request = DataDownloadRequest(
            symbol="BTC/USDT",
            start="2025-12-31",
            end="2025-01-01",
        )
        with pytest.raises(ValueError, match="start must be earlier"):
            service.seed_demo_data(request)


class TestStationServiceTagDataSource:
    def test_tag_invalid_source(self):
        from quantflow.web.service import StationService, DataSourceTagRequest
        from quantflow.web.history import StationHistoryStore
        service = StationService(history_store=StationHistoryStore())
        request = DataSourceTagRequest(data_source="invalid_source")
        with pytest.raises(ValueError, match="data_source must be"):
            service.tag_data_source(request)


class TestStationServiceWorkbench:
    def test_workbench_state_default(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        store = StationHistoryStore()
        service = StationService(history_store=store)
        result = service.workbench_state()
        # Returns a default state, not None
        assert isinstance(result, dict)

    def test_save_workbench_state(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        store = StationHistoryStore()
        service = StationService(history_store=store)
        result = service.save_workbench_state({"panel": "execution"})
        assert result["panel"] == "execution"
        assert "savedAt" in result

    def test_save_workbench_invalid(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        store = StationHistoryStore()
        service = StationService(history_store=store)
        with pytest.raises(ValueError, match="must be a JSON object"):
            service.save_workbench_state("not_a_dict")


class TestStationServiceResearchHistory:
    def test_research_history(self, tmp_path):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        store = StationHistoryStore(base_dir=tmp_path / "history")
        store.append_research_run({"request": {"strategy": "test"}, "result": {"total_return": 0.1}})
        service = StationService(history_store=store)
        result = service.research_history(limit=5)
        assert isinstance(result, list)
        assert len(result) == 1


class TestStationServiceValidationHistory:
    def test_validation_history_normalizes_summary(self, tmp_path):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        store = StationHistoryStore(base_dir=tmp_path / "history")
        # Insert a validation run without a proper summary → triggers _validation_summary
        store.append_validation_run({
            "method": "gate",
            "payload": {"method": "gate", "result": {"decision": "GO", "checks": {"cpcv": {"passed": True}}},
                       "signals": {"entries": 5, "exits": 3, "bars": 100}, "backtest": {}},
        })
        service = StationService(history_store=store)
        result = service.validation_history(limit=5)
        assert isinstance(result, list)


class TestStationServiceMonitoringSnapshot:
    def test_monitoring_snapshot_basic(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]), \
             patch("quantflow.web.service.metrics_registry_snapshot", return_value={"values": {}, "available": False}):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                result = service.monitoring_snapshot(
                    session_snapshot=None,
                    session_history=[],
                    session_events=[],
                )
                assert isinstance(result, dict)
                assert "health" in result
                assert "services" in result
                assert "alerts" in result

    def test_monitoring_snapshot_with_errors(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]), \
             patch("quantflow.web.service.metrics_registry_snapshot", return_value={"values": {}, "available": False}):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                result = service.monitoring_snapshot(
                    session_snapshot={"session_id": "s1", "running": True},
                    session_history=[],
                    session_events=[
                        {"level": "error", "event_type": "risk", "title": "Risk alert", "message": "Drawdown breach"},
                    ],
                )
                assert result["health"]["overall_tone"] == "danger"

    def test_monitoring_snapshot_with_nogo_validation(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        store = StationHistoryStore()
        store.append_validation_run({
            "method": "gate",
            "payload": {"method": "gate", "result": {"decision": "NO-GO", "checks": {"cpcv": {"passed": False}}},
                       "signals": {"entries": 5, "exits": 3, "bars": 100}, "backtest": {}},
            "summary": {
                "method": "gate", "outcome_label": "NO-GO", "outcome_tone": "danger",
                "decision": "NO-GO", "method_label": "Validation Gate",
            },
        })
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]), \
             patch("quantflow.web.service.metrics_registry_snapshot", return_value={"values": {}, "available": False}):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=store)
                result = service.monitoring_snapshot(
                    session_snapshot=None,
                    session_history=[],
                    session_events=[],
                )
                assert result["metrics"]["validation_no_go"] >= 1


class TestStationServiceExecutionSnapshot:
    def test_execution_snapshot_idle(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                result = service.execution_snapshot(
                    session_snapshot=None,
                    session_history=[],
                    session_events=[],
                )
                assert isinstance(result, dict)
                assert result["status"]["label"] == "Execution Idle"

    def test_execution_snapshot_with_running_session(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                session_snapshot = {
                    "session_id": "s1",
                    "running": True,
                    "dashboard": {"status_label": "Running", "status_tone": "accent"},
                    "request": {"mode": "paper", "symbol": "BTC/USDT", "timeframe": "1h", "strategies": ["trend_following"]},
                    "portfolio": {"equity": 100000, "cash": 50000, "market_value": 50000, "drawdown": -0.01},
                    "health": {"running": True, "open_positions": 1, "pending_orders": 0},
                    "kill_switch": {"active": False, "reason": None},
                    "positions": [{"symbol": "BTC/USDT", "quantity": 0.1, "entry_price": 50000, "current_price": 51000, "unrealized_pnl": 100, "market_value": 5100}],
                    "open_orders": [],
                    "telemetry": {"labels": ["t1"], "equity": [100000], "cash": [50000], "market_value": [50000], "drawdown": [-0.01], "open_positions": [1], "pending_orders": [0]},
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:01:00+00:00",
                }
                result = service.execution_snapshot(
                    session_snapshot=session_snapshot,
                    session_history=[session_snapshot],
                    session_events=[],
                )
                assert result["status"]["label"] == "Execution Online"
                assert result["summary"]["position_count"] == 1

    def test_execution_snapshot_with_kill_switch(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                session_snapshot = {
                    "session_id": "s1",
                    "running": False,
                    "dashboard": {"status_label": "Stopped", "status_tone": "muted"},
                    "request": {"mode": "paper", "symbol": "BTC/USDT", "timeframe": "1h", "strategies": []},
                    "portfolio": {"equity": 100000, "cash": 100000, "market_value": 0, "drawdown": 0},
                    "health": {"running": False, "open_positions": 0, "pending_orders": 0},
                    "kill_switch": {"active": True, "reason": "drawdown_breach"},
                    "positions": [],
                    "open_orders": [],
                    "telemetry": {"labels": [], "equity": [], "cash": [], "market_value": [], "drawdown": [], "open_positions": [], "pending_orders": []},
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:01:00+00:00",
                }
                result = service.execution_snapshot(
                    session_snapshot=session_snapshot,
                    session_history=[],
                    session_events=[],
                )
                assert result["status"]["label"] == "Kill Switch Active"
                assert result["status"]["tone"] == "danger"

    def test_execution_snapshot_with_error(self):
        from quantflow.web.service import StationService
        from quantflow.web.history import StationHistoryStore
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service.resolve_config_path") as mock_resolve, \
             patch("quantflow.web.service._docker_available", return_value=False), \
             patch("quantflow.web.service.list_strategy_summaries", return_value=[]):
            mock_resolve.return_value = "/test/config.yaml"
            mock_config = MagicMock()
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_config.monitoring.prometheus_port = 9090
            mock_config.monitoring.grafana_port = 3000
            mock_config.risk.max_drawdown = -0.1
            mock_config.risk.daily_loss_limit = -0.05
            mock_config.risk.weekly_loss_limit = -0.1
            mock_config.risk.kill_switch_enabled = False
            mock_config.execution.mode = "paper"
            mock_config.execution.slippage = 0.001
            mock_config.execution.maker_fee = 0.0002
            mock_config.execution.taker_fee = 0.0005
            mock_load.return_value = mock_config

            mock_store = MagicMock()
            mock_store.list_symbols.return_value = []
            mock_store.close = MagicMock()

            with patch("quantflow.web.service._open_station_store", return_value=mock_store):
                service = StationService(history_store=StationHistoryStore())
                session_snapshot = {
                    "session_id": "s1",
                    "running": False,
                    "last_error": "Connection timeout",
                    "dashboard": {"status_label": "Stopped", "status_tone": "muted"},
                    "request": {"mode": "paper", "symbol": "BTC/USDT", "timeframe": "1h", "strategies": []},
                    "portfolio": {"equity": 100000, "cash": 100000, "market_value": 0, "drawdown": 0},
                    "health": {"running": False, "open_positions": 0, "pending_orders": 0},
                    "kill_switch": {"active": False, "reason": None},
                    "positions": [],
                    "open_orders": [],
                    "telemetry": {"labels": [], "equity": [], "cash": [], "market_value": [], "drawdown": [], "open_positions": [], "pending_orders": []},
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:01:00+00:00",
                }
                result = service.execution_snapshot(
                    session_snapshot=session_snapshot,
                    session_history=[],
                    session_events=[],
                )
                assert result["status"]["label"] == "Execution Degraded"
                assert result["status"]["tone"] == "warning"


class TestQuerySymbolFrame:
    def test_empty_store_returns_demo(self):
        from quantflow.web.service import _query_symbol_frame
        mock_store = MagicMock()
        mock_store.query.return_value = pd.DataFrame()
        frame, source = _query_symbol_frame(mock_store, "BTC/USDT")
        assert source == "demo"
        assert len(frame) > 0  # demo frame

    def test_frame_with_datetime_column(self):
        from quantflow.web.service import _query_symbol_frame
        dates = pd.date_range("2024-01-01", periods=10, freq="D")
        frame_data = pd.DataFrame({
            "datetime": dates,
            "close": [100.0 + i for i in range(10)],
            "data_source": ["okx"] * 10,
        })
        mock_store = MagicMock()
        mock_store.query.return_value = frame_data
        with patch("quantflow.web.service._resolve_frame_data_source", return_value=("okx", {"okx": 10})):
            frame, source = _query_symbol_frame(mock_store, "BTC/USDT")
            assert source == "okx"

    def test_frame_with_timestamp_column_and_filter(self):
        from quantflow.web.service import _query_symbol_frame
        n = 20
        timestamps = list(range(1700000000000, 1700000000000 + n * 86400000, 86400000))
        frame_data = pd.DataFrame({
            "timestamp": timestamps,
            "close": [100.0 + i for i in range(n)],
            "open": [99.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [98.0 + i for i in range(n)],
            "volume": [1000.0] * n,
            "data_source": ["okx"] * n,
        })
        mock_store = MagicMock()
        mock_store.query.return_value = frame_data
        with patch("quantflow.web.service._resolve_frame_data_source", return_value=("okx", {"okx": n})):
            frame, source = _query_symbol_frame(
                mock_store, "BTC/USDT",
                start="2023-11-15", end="2023-11-30",
            )
            assert len(frame) > 0


class TestStationServiceResearch:
    def test_research_basic(self):
        from quantflow.web.service import StationService, ResearchRequest
        from quantflow.web.history import StationHistoryStore
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        frame = pd.DataFrame({
            "close": pd.Series(100.0 + np.arange(100) * 0.5, index=dates),
            "open": pd.Series(99.5 + np.arange(100) * 0.5, index=dates),
            "high": pd.Series(101.0 + np.arange(100) * 0.5, index=dates),
            "low": pd.Series(99.0 + np.arange(100) * 0.5, index=dates),
            "volume": pd.Series(1000.0, index=dates),
        })
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service._load_store") as mock_load_store, \
             patch("quantflow.web.service._query_symbol_frame", return_value=(frame, "demo")), \
             patch("quantflow.web.service.get_strategy_definition") as mock_def:
            mock_config = MagicMock()
            mock_config.data.exchange = "okx"
            mock_config.data.parquet_dir = "/tmp/test"
            mock_config.data.duckdb_path = "/tmp/test.duckdb"
            mock_load.return_value = mock_config
            mock_store = MagicMock()
            mock_store.close = MagicMock()
            mock_load_store.return_value = (mock_config, mock_store)

            mock_strategy = MagicMock()
            entries = pd.Series(False, index=dates)
            exits = pd.Series(False, index=dates)
            mock_strategy.generate_signals.return_value = (entries, exits)
            mock_def.return_value = MagicMock(factory=MagicMock(return_value=mock_strategy))

            service = StationService(history_store=StationHistoryStore())
            request = ResearchRequest(
                strategy="trend_following",
                symbol="BTC/USDT",
                capital=10000.0,
            )
            result = service.research(request)
            assert "result" in result
            assert "chart" in result
            assert "signals" in result
            assert "data_source" in result


class TestStationServiceValidate:
    def test_validate_gate_method(self):
        from quantflow.web.service import StationService, ValidationRequest
        from quantflow.web.history import StationHistoryStore
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        frame = pd.DataFrame({
            "close": pd.Series(100.0 + np.arange(100) * 0.5, index=dates),
            "volume": pd.Series(1000.0, index=dates),
        })
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service._load_store") as mock_load_store, \
             patch("quantflow.web.service._query_symbol_frame", return_value=(frame, "demo")), \
             patch("quantflow.web.service.get_strategy_definition") as mock_def, \
             patch("quantflow.strategy.validation.gate.validation_gate") as mock_gate:
            mock_config = MagicMock()
            mock_load.return_value = mock_config
            mock_store = MagicMock()
            mock_store.close = MagicMock()
            mock_load_store.return_value = (mock_config, mock_store)

            mock_strategy = MagicMock()
            entries = pd.Series(False, index=dates)
            exits = pd.Series(False, index=dates)
            mock_strategy.generate_signals.return_value = (entries, exits)
            mock_def.return_value = MagicMock(
                factory=MagicMock(return_value=mock_strategy),
                param_space={},
            )
            mock_gate.return_value = {"decision": "GO", "checks": {"cpcv": {"passed": True}}}

            service = StationService(history_store=StationHistoryStore())
            request = ValidationRequest(method="gate", strategy="trend_following")
            result = service.validate(request)
            assert "summary" in result
            assert "method" in result

    def test_validate_dsr_method(self):
        from quantflow.web.service import StationService, ValidationRequest
        from quantflow.web.history import StationHistoryStore
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        frame = pd.DataFrame({
            "close": pd.Series(100.0 + np.arange(100) * 0.5, index=dates),
            "volume": pd.Series(1000.0, index=dates),
        })
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service._load_store") as mock_load_store, \
             patch("quantflow.web.service._query_symbol_frame", return_value=(frame, "demo")), \
             patch("quantflow.web.service.get_strategy_definition") as mock_def, \
             patch("quantflow.strategy.validation.dsr.deflated_sharpe_ratio") as mock_dsr:
            mock_config = MagicMock()
            mock_load.return_value = mock_config
            mock_store = MagicMock()
            mock_store.close = MagicMock()
            mock_load_store.return_value = (mock_config, mock_store)

            mock_strategy = MagicMock()
            entries = pd.Series(False, index=dates)
            exits = pd.Series(False, index=dates)
            mock_strategy.generate_signals.return_value = (entries, exits)
            mock_def.return_value = MagicMock(
                factory=MagicMock(return_value=mock_strategy),
                param_space={},
            )
            mock_dsr.return_value = {"passed": True, "dsr": 0.05}

            service = StationService(history_store=StationHistoryStore())
            request = ValidationRequest(method="dsr", strategy="trend_following")
            result = service.validate(request)
            assert result["method"] == "dsr"

    def test_validate_pbo_method(self):
        from quantflow.web.service import StationService, ValidationRequest
        from quantflow.web.history import StationHistoryStore
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        frame = pd.DataFrame({
            "close": pd.Series(100.0 + np.arange(100) * 0.5, index=dates),
            "volume": pd.Series(1000.0, index=dates),
        })
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service._load_store") as mock_load_store, \
             patch("quantflow.web.service._query_symbol_frame", return_value=(frame, "demo")), \
             patch("quantflow.web.service.get_strategy_definition") as mock_def, \
             patch("quantflow.strategy.validation.pbo.probability_of_overfitting") as mock_pbo:
            mock_config = MagicMock()
            mock_load.return_value = mock_config
            mock_store = MagicMock()
            mock_store.close = MagicMock()
            mock_load_store.return_value = (mock_config, mock_store)

            mock_strategy = MagicMock()
            entries = pd.Series(False, index=dates)
            exits = pd.Series(False, index=dates)
            mock_strategy.generate_signals.return_value = (entries, exits)
            mock_def.return_value = MagicMock(
                factory=MagicMock(return_value=mock_strategy),
                param_space={},
            )
            mock_pbo.return_value = {"passed": True, "pbo": 0.2, "overfit_paths": 2, "total_paths": 10}

            service = StationService(history_store=StationHistoryStore())
            request = ValidationRequest(method="pbo", strategy="trend_following")
            result = service.validate(request)
            assert result["method"] == "pbo"

    def test_validate_wfo_method(self):
        from quantflow.web.service import StationService, ValidationRequest
        from quantflow.web.history import StationHistoryStore
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        frame = pd.DataFrame({
            "close": pd.Series(100.0 + np.arange(100) * 0.5, index=dates),
            "volume": pd.Series(1000.0, index=dates),
        })
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service._load_store") as mock_load_store, \
             patch("quantflow.web.service._query_symbol_frame", return_value=(frame, "demo")), \
             patch("quantflow.web.service.get_strategy_definition") as mock_def, \
             patch("quantflow.strategy.validation.wfo.walk_forward_optimization") as mock_wfo:
            mock_config = MagicMock()
            mock_load.return_value = mock_config
            mock_store = MagicMock()
            mock_store.close = MagicMock()
            mock_load_store.return_value = (mock_config, mock_store)

            mock_strategy = MagicMock()
            entries = pd.Series(False, index=dates)
            exits = pd.Series(False, index=dates)
            mock_strategy.generate_signals.return_value = (entries, exits)
            mock_def.return_value = MagicMock(
                factory=MagicMock(return_value=mock_strategy),
                param_space={},
            )
            mock_wfo.return_value = {"passed": True, "oos_sharpe_mean": 1.0}

            service = StationService(history_store=StationHistoryStore())
            request = ValidationRequest(method="wfo", strategy="trend_following")
            result = service.validate(request)
            assert result["method"] == "wfo"

    def test_validate_cpcv_method(self):
        from quantflow.web.service import StationService, ValidationRequest
        from quantflow.web.history import StationHistoryStore
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        frame = pd.DataFrame({
            "close": pd.Series(100.0 + np.arange(100) * 0.5, index=dates),
            "volume": pd.Series(1000.0, index=dates),
        })
        with patch("quantflow.web.service.load_config") as mock_load, \
             patch("quantflow.web.service._load_store") as mock_load_store, \
             patch("quantflow.web.service._query_symbol_frame", return_value=(frame, "demo")), \
             patch("quantflow.web.service.get_strategy_definition") as mock_def, \
             patch("quantflow.strategy.validation.cpcv.cpcv_backtest") as mock_cpcv:
            mock_config = MagicMock()
            mock_load.return_value = mock_config
            mock_store = MagicMock()
            mock_store.close = MagicMock()
            mock_load_store.return_value = (mock_config, mock_store)

            mock_strategy = MagicMock()
            entries = pd.Series(False, index=dates)
            exits = pd.Series(False, index=dates)
            mock_strategy.generate_signals.return_value = (entries, exits)
            mock_def.return_value = MagicMock(
                factory=MagicMock(return_value=mock_strategy),
                param_space={},
            )
            mock_cpcv.return_value = {"passed": True, "pbo": 0.2, "n_paths": 10, "oos_sharpe_mean": 1.2}

            service = StationService(history_store=StationHistoryStore())
            request = ValidationRequest(method="cpcv", strategy="trend_following")
            result = service.validate(request)
            assert result["method"] == "cpcv"
