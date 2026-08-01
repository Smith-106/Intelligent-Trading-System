"""Additional coverage for the consensus ZigZag indicator."""

from __future__ import annotations

import pandas as pd

from quantflow.indicators.zigzag import ZigZagIndicator, _merge_pivot_runs, _zigzag_single


class TestZigZagIndicatorExtra:
    def test_compute_pivot_sequence_uses_default_thresholds_and_handles_no_pivots(self) -> None:
        indicator = ZigZagIndicator()
        high = pd.Series([100.0, 100.5, 100.7], dtype=float)
        low = pd.Series([99.5, 99.7, 99.8], dtype=float)
        timestamps = pd.Series([1, 2, 3], dtype=int)

        result = indicator.compute_pivot_sequence(high, low, timestamps, thresholds=None)

        assert result.pivots == []
        assert result.overlap_ratio == 0.0
        assert result.thresholds_used == [0.03, 0.05, 0.08, 0.12, 0.15]

    def test_compute_pivot_sequence_uses_zero_timestamp_when_index_is_out_of_range(
        self, monkeypatch
    ) -> None:
        indicator = ZigZagIndicator()
        high = pd.Series([100.0, 110.0, 105.0], dtype=float)
        low = pd.Series([99.0, 100.0, 95.0], dtype=float)
        timestamps = pd.Series([111], dtype=int)

        monkeypatch.setattr(
            "quantflow.indicators.zigzag._zigzag_single",
            lambda *args, **kwargs: pd.DataFrame(
                [{"pivot_idx": 2, "pivot_price": 95.0, "pivot_type": -1}]
            ),
        )

        result = indicator.compute_pivot_sequence(
            high, low, timestamps, thresholds=[0.05], min_overlap_ratio=1.0
        )

        assert len(result.pivots) == 1
        assert result.pivots[0].timestamp == 0
        assert result.overlap_ratio == 1.0


class TestZigZagHelpersExtra:
    def test_zigzag_single_handles_short_series_and_initial_upward_break(self) -> None:
        short = _zigzag_single(pd.Series([100.0, 101.0]), pd.Series([99.0, 100.0]), threshold=0.05)
        assert short.empty

        high = pd.Series([100.0, 107.0, 112.0, 120.0], dtype=float)
        low = pd.Series([99.0, 100.0, 104.0, 108.0], dtype=float)

        result = _zigzag_single(high, low, threshold=0.05)

        assert result.iloc[0].to_dict() == {"pivot_idx": 0, "pivot_price": 99.0, "pivot_type": -1}
        assert result.iloc[-1]["pivot_type"] == 1

    def test_merge_pivot_runs_handles_empty_runs_empty_entries_and_no_consensus(self) -> None:
        assert _merge_pivot_runs([]).empty

        empty_entries = _merge_pivot_runs(
            [pd.DataFrame(columns=["pivot_idx", "pivot_price", "pivot_type"])]
        )
        assert empty_entries.empty

        no_consensus = _merge_pivot_runs(
            [
                pd.DataFrame([{"pivot_idx": 1, "pivot_price": 100.0, "pivot_type": 1}]),
                pd.DataFrame([{"pivot_idx": 10, "pivot_price": 110.0, "pivot_type": -1}]),
            ],
            min_overlap=2,
            bar_tolerance=0,
        )
        assert no_consensus.empty

    def test_low_volatility_fallback_uses_median_threshold_when_consensus_empty(
        self, monkeypatch
    ) -> None:
        """ISS-20260613-007: when min_overlap > 80% yields no consensus pivots,
        fall back to the single ZigZag run with the median parameter value."""
        indicator = ZigZagIndicator()
        high = pd.Series([100.0] * 20, dtype=float)
        low = pd.Series([99.0] * 20, dtype=float)
        timestamps = pd.Series(list(range(20)), dtype=int)

        # Monkeypatch _merge_pivot_runs to return empty — simulates low-volatility
        # scenario where no pivot group reaches min_overlap.
        monkeypatch.setattr(
            "quantflow.indicators.zigzag._merge_pivot_runs",
            lambda *args, **kwargs: pd.DataFrame(
                columns=["pivot_idx", "pivot_price", "pivot_type", "overlap_count"]
            ),
        )

        # Patch _zigzag_single to return a known pivot only for the median threshold.
        median_threshold = 0.08  # middle of [0.03, 0.05, 0.08, 0.12, 0.15]
        fake_pivot = pd.DataFrame([{"pivot_idx": 5, "pivot_price": 100.0, "pivot_type": 1}])

        def _fake_zigzag(h, low_prices, threshold):
            if abs(threshold - median_threshold) < 1e-9:
                return fake_pivot.copy()
            return pd.DataFrame(columns=["pivot_idx", "pivot_price", "pivot_type"])

        monkeypatch.setattr("quantflow.indicators.zigzag._zigzag_single", _fake_zigzag)

        result = indicator.compute_pivot_sequence(
            high,
            low,
            timestamps,
            thresholds=[0.03, 0.05, 0.08, 0.12, 0.15],
            min_overlap_ratio=0.8,
        )

        # Fallback should produce exactly one pivot from the median-threshold run.
        assert len(result.pivots) == 1
        assert result.pivots[0].index == 5
        assert result.pivots[0].price == 100.0
