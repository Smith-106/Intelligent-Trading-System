"""ISS-20260718-002: Recursive indicator dependency analysis tests."""

from quantflow.strategy.validation.recursive import (
    RecursiveReport,
    _detect_cycles,
    scan_recursive,
)


class TestRecursiveReport:
    def test_default_values(self) -> None:
        report = RecursiveReport(strategy="test", passed=True)
        assert report.cycles == []
        assert report.indicator_deps == {}

    def test_to_dict(self) -> None:
        report = RecursiveReport(
            strategy="test",
            passed=False,
            cycles=[["a", "b", "a"]],
            indicator_deps={"a": ["b"], "b": ["a"]},
        )
        d = report.to_dict()
        assert d["passed"] is False
        assert len(d["cycles"]) == 1


class TestDetectCycles:
    def test_no_cycles(self) -> None:
        graph = {"a": ["b", "c"], "b": ["c"], "c": []}
        assert _detect_cycles(graph) == []

    def test_simple_cycle(self) -> None:
        graph = {"a": ["b"], "b": ["a"]}
        cycles = _detect_cycles(graph)
        assert len(cycles) >= 1

    def test_self_loop(self) -> None:
        graph = {"a": ["a"]}
        cycles = _detect_cycles(graph)
        assert len(cycles) >= 1

    def test_longer_cycle(self) -> None:
        graph = {"a": ["b"], "b": ["c"], "c": ["a"]}
        cycles = _detect_cycles(graph)
        assert len(cycles) >= 1

    def test_dag_no_cycles(self) -> None:
        graph = {"rsi": ["close"], "macd": ["close"], "signal": ["rsi", "macd"]}
        assert _detect_cycles(graph) == []


class TestScanRecursive:
    def test_scan_simple_strategy(self) -> None:
        """Scan a strategy with no recursive deps — should pass."""
        from quantflow.strategy.templates.trend_following import TrendFollowingStrategy

        report = scan_recursive(TrendFollowingStrategy)
        assert report.strategy == "TrendFollowingStrategy"
        assert report.passed is True  # No circular deps expected

    def test_scan_returns_source_path(self) -> None:
        from quantflow.strategy.templates.trend_following import TrendFollowingStrategy

        report = scan_recursive(TrendFollowingStrategy)
        assert report.source_path is not None
        assert "trend_following" in report.source_path
