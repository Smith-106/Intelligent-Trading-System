"""Tests for the static look-ahead leak scanner (deep-research F2 / P0.2)."""

from __future__ import annotations

import pandas as pd  # noqa: F401  (used in synthetic strategy bodies)
import pytest

from quantflow.strategy.validation.lookahead import LookaheadReport, scan_strategy


class _LeakyStrategy:
    """Synthetic strategy exhibiting every masked-aggregation leak shape."""

    def generate_signals(self, df):  # type: ignore[no-untyped-def]
        import numpy as np

        rsi = df["close"]
        entries = rsi > 30
        exits = rsi < 70
        # Shape 1 direct: series[mask].agg()  -> high
        target = rsi[entries].mean()
        # Shape 2: np.mean(series[mask])      -> medium
        avg = np.mean(rsi[entries])
        # Shape 1 chain: series[mask].rolling(...).mean() -> high (single)
        smooth = rsi[entries].rolling(5).mean()
        # touch the leak values so they are not F841-unused; their sole purpose
        # is to be scanned by the AST detector above.
        _ = (target, avg, smooth)
        return entries, exits


class _CleanStrategy:
    """Reference strategy with no masked-aggregation leaks."""

    def generate_signals(self, df):  # type: ignore[no-untyped-def]
        rsi = df["close"]
        prior = rsi.shift(1)  # safe: prior-bar reference, not a mask slice
        entries = prior > 30
        exits = prior < 70
        return entries, exits


class _MissingMethodStrategy:
    """Strategy with neither generate_signals nor on_bar — scanner tolerates."""

    pass


def test_clean_strategy_passes() -> None:
    report = scan_strategy(_CleanStrategy())
    assert isinstance(report, LookaheadReport)
    assert report.passed
    assert report.findings == []
    assert report.high_severity_count == 0
    assert "generate_signals" in report.scanned_methods


def test_leaky_strategy_flags_all_three_shapes() -> None:
    report = scan_strategy(_LeakyStrategy())
    assert not report.passed
    assert len(report.findings) == 3, (
        f"expected 3 findings (1 direct + 1 wrapped + 1 chain), got "
        f"{len(report.findings)}: {[f.pattern for f in report.findings]}"
    )
    patterns = {f.pattern for f in report.findings}
    assert "rsi[entries].mean()" in patterns
    assert "mean(rsi[entries])" in patterns
    assert "rsi[entries].rolling(...).mean()" in patterns


def test_chain_does_not_duplicate_findings() -> None:
    """series[mask].rolling(...).mean() must produce exactly ONE finding."""
    report = scan_strategy(_LeakyStrategy())
    rolling_findings = [f for f in report.findings if "rolling" in f.pattern]
    assert len(rolling_findings) == 1


def test_high_and_medium_severity_classification() -> None:
    report = scan_strategy(_LeakyStrategy())
    by_pattern = {f.pattern: f.severity for f in report.findings}
    assert by_pattern["rsi[entries].mean()"] == "high"
    assert by_pattern["rsi[entries].rolling(...).mean()"] == "high"
    # np.mean(...) wrapped call is medium (could be a legitimate use, needs review)
    assert by_pattern["mean(rsi[entries])"] == "medium"


def test_finding_carries_source_location_and_note() -> None:
    report = scan_strategy(_LeakyStrategy())
    f = next(f for f in report.findings if f.pattern == "rsi[entries].mean()")
    assert f.line > 0
    assert f.column >= 0
    assert "rsi[entries].mean()" in f.snippet
    assert "forward-fill" in f.note or "forward fill" in f.note


def test_missing_methods_does_not_crash() -> None:
    report = scan_strategy(_MissingMethodStrategy())
    assert report.scanned_methods == []
    assert report.passed  # no leaks in code that doesn't exist


def test_summary_string_format() -> None:
    clean = scan_strategy(_CleanStrategy())
    assert "PASS" in clean.summary()
    leaky = scan_strategy(_LeakyStrategy())
    assert "FAIL" in leaky.summary()
    assert "3" in leaky.summary()


@pytest.mark.parametrize("name", ["entries", "exits", "mask", "signals"])
def test_recognized_mask_names_trigger(name: str) -> None:
    """Each canonical mask name must be in the recognized set."""
    from quantflow.strategy.validation.lookahead import _MASK_NAMES

    assert name in _MASK_NAMES


def test_real_strategies_have_no_false_positives() -> None:
    """All shipped strategies must pass the scanner (regression guard).

    The v0.1.3 perf run introduced masked-aggregation leaks (since fixed).
    This test freezes the current clean state so a future perf change cannot
    reintroduce them silently.
    """
    from quantflow.cli.main import _get_strategy_specs

    for name, (factory, _space) in _get_strategy_specs().items():
        report = scan_strategy(factory(None))
        assert report.passed, (
            f"{name} flagged {len(report.findings)} look-ahead leak(s): "
            f"{[f.pattern for f in report.findings]}"
        )
