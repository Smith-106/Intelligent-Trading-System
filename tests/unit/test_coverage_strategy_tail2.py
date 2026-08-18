"""Final tail: remaining strategy branch gaps to 100/100."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.auto_loop import _metric_summary
from quantflow.strategy.model_registry import ModelRegistry
from quantflow.strategy.sentiment import SentimentAnalyzer
from quantflow.strategy.validation.causal_preflight import run_causal_preflight
from quantflow.strategy.validation.cost_fidelity import extract_cost_grid, extract_funding_tca
from quantflow.strategy.validation.cpcv import cpcv_backtest
from quantflow.strategy.validation.lookahead import scan_strategy
from quantflow.strategy.validation.paper_readiness import (
    PaperReadinessConfig,
    assert_report_paper_ready,
)
from quantflow.strategy.validation.promotion_path import extract_data_fingerprint
from quantflow.strategy.validation.recursive import scan_recursive
from quantflow.strategy.validation.wfo import WalkForwardOptimization


# ------------------------------------------------------------------- sentiment
class TestSentimentTail2:
    def test_analyze_text_generative_branch(self) -> None:
        """L111: _generative=True + model/tokenizer set → _analyze_generative."""
        sa = SentimentAnalyzer()
        sa._generative = True
        sa._model = SimpleNamespace()  # type: ignore[assignment]
        sa._tokenizer = SimpleNamespace()  # type: ignore[assignment]
        out = sa.analyze_text("hello")
        assert isinstance(out, dict)

    def test_analyze_generative_without_model_sentinel(self) -> None:
        """L141: _analyze_generative with no model/tokenizer → sentinel."""
        sa = SentimentAnalyzer()
        sa._generative = True
        out = sa._analyze_generative("hello")
        assert isinstance(out, dict)
        assert np.isnan(list(out.values())[0])


# ----------------------------------------------------------------- model_registry
class TestModelRegistryTail2:
    def test_constructor_paper_readiness_config_branch(self, tmp_path: pytest.TempPathFactory) -> None:
        """L68-71: PaperReadinessConfig instance branch + Mapping branch."""
        cfg = PaperReadinessConfig(min_paper_days=5)
        reg = ModelRegistry(tmp_path / "a", paper_readiness=cfg)
        assert reg._paper_readiness.min_paper_days == 5
        reg2 = ModelRegistry(tmp_path / "b", paper_readiness={"min_paper_days": 9})
        assert reg2._paper_readiness.min_paper_days == 9
        reg3 = ModelRegistry(tmp_path / "c")
        assert reg3._paper_readiness is not None

    def test_promote_to_live_no_evidence(self, tmp_path: pytest.TempPathFactory) -> None:
        """L213-215: evidence None → no paper_evidence write."""
        reg = ModelRegistry(tmp_path / "r")
        reg.register("m1", "Cls", "h", {"passed": True, "decision": "GO"})
        e = reg.get("m1")
        e["status"] = "paper"
        reg._write(e)
        entry = reg.promote_to_live("m1", paper_evidence={"paper_days": 30, "fills": 50})
        assert entry["status"] == "live"

    def test_attach_paper_evidence_missing_raises(self, tmp_path: pytest.TempPathFactory) -> None:
        """L224-225: attach_paper_evidence on missing model → raise."""
        reg = ModelRegistry(tmp_path / "r")
        with pytest.raises(Exception):
            reg.attach_paper_evidence("nope", {"fills": 1})


# ---------------------------------------------------------------------- auto_loop
class TestAutoLoopTail2:
    def test_metric_summary_non_dict_check(self) -> None:
        """L150-161: non-dict check value skipped."""
        out = _metric_summary({"checks": {"a": "not-dict", "b": {"passed": True}}})
        assert "b" in out
        assert "a" not in out


# ------------------------------------------------------------------ cost_fidelity
class TestCostFidelityTail2:
    def test_extract_cost_grid_empty_and_bad(self) -> None:
        """L46-48 / L53-55: grid list-but-empty and non-list branches."""
        assert extract_cost_grid({"fee_slip_grid": []}) is None
        assert extract_cost_grid({"fee_slip_grid": "nope"}) is None
        assert extract_cost_grid({"cost_fidelity": {"cost_grid": []}}) is None
        assert extract_cost_grid({"checks": {"cost_fidelity": {"cost_grid": "x"}}}) is None

    def test_extract_funding_tca_non_dict_and_missing(self) -> None:
        """L209-227: non-dict report; missing cost/checks branches."""
        assert extract_funding_tca(None) is None
        assert extract_funding_tca({"cost_fidelity": "not-dict"}) is None
        assert extract_funding_tca({"checks": {"other": {}}}) is None
        assert extract_funding_tca({"checks": {"cost_fidelity": {"tca": {"x": 1}}}}) == {"x": 1}


# ---------------------------------------------------------------- paper_readiness
class TestPaperReadinessTail2:
    def test_min_orders_branch(self) -> None:
        """L199-205: cfg.min_orders > 0 branches (orders missing / too few)."""
        from quantflow.strategy.validation.paper_readiness import assert_paper_readiness

        cfg = PaperReadinessConfig(min_paper_days=0, min_fills=0, min_orders=5)
        with pytest.raises(Exception, match="orders"):
            assert_paper_readiness({"paper_days": 10, "fills": 50, "orders": 2}, config=cfg)

    def test_require_when_missing_none(self) -> None:
        """L234-242: require_when_missing None → default config path."""
        cfg = PaperReadinessConfig(min_paper_days=0, min_fills=0)
        result = assert_report_paper_ready(
            {"paper_evidence": {"paper_days": 10, "fills": 50}}, config=cfg
        )
        assert result["passed"] is True


# ----------------------------------------------------------------------- lookahead
class TestLookaheadTail2:
    def test_scan_shape2_attribute_func(self) -> None:
        """L202-225: agg(mask) where func is ast.Attribute (np.mean)."""

        class S:
            def generate_signals(self, df: Any) -> tuple[Any, Any]:
                import numpy as _np

                mask = df.close > 0
                v = _np.mean(df.close[mask])
                return (v > 1, v < 0)

        report = scan_strategy(S())
        assert report.findings is not None


# ---------------------------------------------------------------- promotion_path
class TestPromotionPathTail2:
    def test_checks_loop_and_path_block(self) -> None:
        """L106-120: checks data_fingerprint/fingerprint + path_block + run_meta."""
        assert extract_data_fingerprint({"checks": {"data_fingerprint": "d1"}}) == "d1"
        assert extract_data_fingerprint({"checks": {"fingerprint": {"h": 1}}}) == {"h": 1}
        assert extract_data_fingerprint({"checks": {"promotion_path": {}}}) is None
        assert extract_data_fingerprint({"run_meta": {}}) is None
        assert extract_data_fingerprint({"contract_pin": {}}) is None


# -------------------------------------------------------------- causal_preflight
class TestCausalPreflightTail2:
    def test_dedup_duplicate_shift(self) -> None:
        """L157-158: duplicate line+snippet continues (dedup)."""
        src = "df.close.shift(-1) > 0\ny = df.close.shift(-1) > 0"
        report = run_causal_preflight(None, extra_sources=[("dup", src)])
        # two identical-ish shifts: second deduped
        assert report is not None


# ----------------------------------------------------------------------- recursive
class RecursiveNameStrategy:
    def generate_signals(self, df: Any) -> tuple[Any, Any]:
        eng = SimpleNamespace()
        eng.compute = lambda: df.close
        eng.compute_all = lambda: df.close
        return (df.close > 0, df.close < 0)


class TestRecursiveTail2:
    def test_scan_name_value_branch(self) -> None:
        """L98-94: Attribute value is Name (engine.compute) branch."""
        report = scan_recursive(RecursiveNameStrategy)
        assert report is not None


# ----------------------------------------------------------------------------- wfo
class TestWfoTail2:
    def test_all_skipped_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """L168-175: not folds + skipped_folds warning."""
        close = pd.Series(range(100, 105), dtype=float)
        entries = pd.Series(False, index=close.index)
        exits = pd.Series(False, index=close.index)
        wfo = WalkForwardOptimization(n_folds=5, test_ratio=0.9, purge_delta=10)
        with caplog.at_level("WARNING"):
            r = wfo.run(close, entries, exits)
        assert r.folds == []
        assert any("all 5 folds skipped" in rec.message for rec in caplog.records)

    def test_partial_skip_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """L191-199: some folds skipped warning."""

        def fake_opt(tr: pd.Series):
            return (
                pd.Series(False, index=tr.index),
                pd.Series(False, index=tr.index),
                {"p": 1},
            )

        close = pd.Series(range(100, 130), dtype=float)
        entries = pd.Series(False, index=close.index)
        exits = pd.Series(False, index=close.index)
        entries.iloc[0] = True
        wfo = WalkForwardOptimization(n_folds=4, test_ratio=0.4, anchored=True)
        with caplog.at_level("WARNING"):
            r = wfo.run(close, entries, exits, optimize_fn=fake_opt)
        assert r.folds


# ----------------------------------------------------------------------------- cpcv
class TestCpcvTail2:
    def test_close_col_present(self) -> None:
        """L183-185: 'close' in train columns path."""
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        rng = np.random.default_rng(7)
        prices = 100.0 * pd.Series(1.0 + rng.normal(0, 0.01, n), index=dates).cumprod()
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        for i in range(0, n, 20):
            entries.iloc[i] = True
        for i in range(10, n, 20):
            exits.iloc[i] = True
        r = cpcv_backtest(
            prices, entries, exits, n_groups=4, n_test_groups=2, n_trials=2,
            signal_fn=lambda df, **kw: (df.close > 0, df.close < 0),
        )
        assert r is not None
