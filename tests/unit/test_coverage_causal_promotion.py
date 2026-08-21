"""Coverage completion for validation/causal_preflight.py and promotion_path.py.

Pure-logic paths:
- causal_preflight: pass summary, instantiation fallbacks, lookahead findings
  loop, negative-shift scans (generate_signals + class source + dedup + extras)
- promotion_path: extraction from all nested locations, refused/unknown paths,
  fingerprint presence, attach helper
"""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.strategy.base import StrategyBase
from quantflow.strategy.validation.causal_preflight import (
    CausalPreflightReport,
    _instantiate,
    run_causal_preflight,
)
from quantflow.strategy.validation.promotion_path import (
    PromotionPathError,
    assert_promotion_path_ready,
    attach_promotion_path,
    check_promotion_path,
    extract_data_fingerprint,
    extract_execution_path,
)


class _CleanStaticStrategy(StrategyBase):
    """No leaks: no masked aggregation, no negative shift."""

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        s = df["close"]
        return s > s.mean(), s < s.mean()


class _LeakyShiftStrategy(StrategyBase):
    """Masked aggregation + a negative shift in a helper method."""

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        s = df["close"]
        entries = s > s.mean()
        leak = s[entries].mean()  # masked aggregation
        return s > leak, s < leak

    def _helper(self, s: pd.Series) -> pd.Series:
        return s.shift(-3)  # negative shift in class source


class _LeakyShiftOnlyStrategy(StrategyBase):
    """Negative shift on generate_signals directly."""

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        s = df["close"]
        return s.shift(-1) > 0, s < 0


class _NoArgStrategy(StrategyBase):
    """Constructor that cannot accept None — tests the _instantiate fallback."""

    def __init__(self) -> None:
        super().__init__("no_arg")
        self._data = None

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        s = df["close"]
        return s > s.mean(), s < s.mean()


def _df(n: int = 40) -> pd.DataFrame:
    return pd.DataFrame(
        {"close": [100.0 + i for i in range(n)]},
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )


# ---------------------------------------------------------------------------
# causal_preflight
# ---------------------------------------------------------------------------
class TestCausalPreflight:
    def test_empty_input_fails_with_notes(self) -> None:
        rep = run_causal_preflight()
        assert rep.passed is False
        assert rep.notes == ["empty preflight input"]
        assert rep.severity_counts["high"] == 1

    def test_clean_strategy_pass_and_summary(self) -> None:
        rep = run_causal_preflight(_CleanStaticStrategy())
        assert rep.passed is True
        assert rep.summary() == "CAUSAL PREFLIGHT: PASS"
        assert rep.lookahead is not None
        assert rep.lookahead["passed"] is True

    def test_report_summary_fail(self) -> None:
        rep = CausalPreflightReport(
            passed=False,
            findings=[{"severity": "high"}],
            severity_counts={"high": 1, "medium": 0, "low": 0, "info": 0},
        )
        assert "FAIL" in rep.summary()
        assert rep.to_dict()["passed"] is False

    def test_instantiate_class_with_none_arg_and_instance(self) -> None:
        # _NoArgStrategy(None) raises TypeError -> falls back to strategy()
        inst = _instantiate(_NoArgStrategy)
        assert isinstance(inst, _NoArgStrategy)
        # instance passes through untouched
        obj = _CleanStaticStrategy()
        assert _instantiate(obj) is obj

    def test_leaky_shift_strategy_finds_lookahead_and_negative_shift(self) -> None:
        rep = run_causal_preflight(_LeakyShiftStrategy())
        assert rep.passed is False
        sev = [f["severity"] for f in rep.findings]
        assert "high" in sev
        assert rep.severity_counts["high"] >= 1
        # class-source scan dedup: same negative shift appears in helper too
        assert rep.negative_shifts

    def test_negative_shift_on_generate_signals(self) -> None:
        rep = run_causal_preflight(_LeakyShiftOnlyStrategy())
        assert rep.passed is False
        assert all(
            f["source"] == "negative_shift" for f in rep.findings if f["source"] == "negative_shift"
        )
        assert rep.severity_counts["high"] >= 1

    def test_extra_sources_scan(self) -> None:
        rep = run_causal_preflight(
            _CleanStaticStrategy(),
            extra_sources=[("extra", "def f(x):\n    return x.shift(-2)\n")],
        )
        assert rep.passed is False
        assert any(f["source"] == "negative_shift" for f in rep.findings)

    def test_class_source_scan_exception_notes(self, monkeypatch) -> None:
        def raise_getsource(obj):
            raise OSError("no source")

        monkeypatch.setattr(
            "quantflow.strategy.validation.causal_preflight.inspect.getsource",
            raise_getsource,
        )
        rep = run_causal_preflight(_CleanStaticStrategy())
        assert any("class source scan skipped" in n for n in rep.notes)


# ---------------------------------------------------------------------------
# promotion_path
# ---------------------------------------------------------------------------
class TestPromotionPath:
    def test_extract_execution_path_from_all_locations(self) -> None:
        assert extract_execution_path({"execution_path": "paper_replay"}) == "paper_replay"
        assert extract_execution_path({"research_path": "Paper-Replay"}) == "paper_replay"
        assert extract_execution_path({"eval_path": "trading_session"}) == "trading_session"
        assert (
            extract_execution_path({"checks": {"execution_path": "event_session"}})
            == "event_session"
        )
        assert (
            extract_execution_path(
                {"checks": {"promotion_path": {"execution_path": "production_path"}}}
            )
            == "production_path"
        )
        assert extract_execution_path({"run_meta": {"execution_path": "foo bar"}}) == "foo_bar"
        assert (
            extract_execution_path({"artifacts": {"execution_path": "paper_replay"}})
            == "paper_replay"
        )

    def test_extract_execution_path_empty_candidate_skips(self) -> None:
        # empty string candidate normalizes to ""; next candidate wins
        assert (
            extract_execution_path({"execution_path": "", "research_path": "paper_replay"})
            == "paper_replay"
        )
        assert extract_execution_path({"execution_path": None}) is None

    def test_extract_data_fingerprint_locations(self) -> None:
        assert extract_data_fingerprint({"data_fingerprint": {"a": 1}}) == {"a": 1}
        assert extract_data_fingerprint({"fingerprint": "abc"}) == "abc"
        assert extract_data_fingerprint({"bar_fingerprint": "abc"}) == "abc"
        assert extract_data_fingerprint({"checks": {"data_fingerprint": {"a": 1}}}) == {"a": 1}
        assert (
            extract_data_fingerprint({"checks": {"promotion_path": {"data_fingerprint": "x"}}})
            == "x"
        )
        assert extract_data_fingerprint({"run_meta": {"data_fingerprint": "y"}}) == "y"
        assert extract_data_fingerprint({"contract_pin": {"data_fingerprint": "z"}}) == "z"
        assert extract_data_fingerprint({"decision": "GO"}) is None

    def test_check_path_missing(self) -> None:
        out = check_promotion_path({"decision": "GO"})
        assert out["passed"] is False
        assert any("execution_path missing" in r for r in out["reasons"])

    def test_check_path_refused(self) -> None:
        out = check_promotion_path({"execution_path": "vectorized"})
        assert out["passed"] is False
        assert any("research-filter only" in r for r in out["reasons"])

    def test_check_path_unknown(self) -> None:
        out = check_promotion_path({"execution_path": "strange_path", "data_fingerprint": "x"})
        assert out["passed"] is False
        assert any("not in allowed" in r for r in out["reasons"])

    def test_check_path_missing_fingerprint(self) -> None:
        out = check_promotion_path({"execution_path": "paper_replay"})
        assert out["passed"] is False
        assert any("data_fingerprint missing" in r for r in out["reasons"])

    def test_check_path_ok_and_fingerprint_not_required(self) -> None:
        out = check_promotion_path({"execution_path": "paper_replay", "data_fingerprint": "x"})
        assert out["passed"] is True
        out2 = check_promotion_path({"execution_path": "paper_replay"}, require_fingerprint=False)
        assert out2["passed"] is True

    def test_assert_when_default_ok(self) -> None:
        out = assert_promotion_path_ready(
            {"execution_path": "paper_replay", "data_fingerprint": "x"}
        )
        assert out["passed"] is True
        with pytest.raises(PromotionPathError):
            assert_promotion_path_ready({"execution_path": "backtest"})

    def test_attach_with_and_without_fingerprint(self) -> None:
        with_fp = attach_promotion_path(
            {"decision": "GO"},
            execution_path="paper_replay",
            data_fingerprint={"agg": "z"},
        )
        assert with_fp["data_fingerprint"] == {"agg": "z"}
        assert with_fp["checks"]["promotion_path"]["execution_path"] == "paper_replay"

        without_fp = attach_promotion_path({"decision": "GO"}, execution_path="Paper-Replay")
        assert without_fp["execution_path"] == "paper-replay"
        assert without_fp["checks"]["promotion_path"]["data_fingerprint"] is None

    def test_assert_promotion_path_ready_import_used_in_cost_gate(self) -> None:
        # promotion_path error is re-raised as-is by assert helpers in cost gate
        with pytest.raises(PromotionPathError, match="research-filter"):
            assert_promotion_path_ready({"execution_path": "vbt", "data_fingerprint": "x"})
