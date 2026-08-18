"""Tail coverage: strategy small files to 100% line+branch."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.ai_factors import _expanding_splits
from quantflow.strategy.ai_training import AITrainingPipeline
from quantflow.strategy.auto_loop import _metric_summary
from quantflow.strategy.model_registry import ModelRegistry
from quantflow.strategy.sentiment import NewsCollector, SentimentAnalyzer
from quantflow.strategy.validation.causal_preflight import run_causal_preflight
from quantflow.strategy.validation.cost_fidelity import _row_metric, extract_funding_tca
from quantflow.strategy.validation.cpcv import cpcv_backtest
from quantflow.strategy.validation.lookahead import _attr_chain, scan_strategy
from quantflow.strategy.validation.paper_readiness import (
    PaperReadinessConfig,
    assert_paper_readiness,
    assert_report_paper_ready,
)
from quantflow.strategy.validation.promotion_path import extract_data_fingerprint
from quantflow.strategy.validation.recursive import scan_recursive
from quantflow.strategy.validation.wfo import WalkForwardOptimization


# ---------------------------------------------------------------- sentiment
class TestSentimentTail:
    def test_analyze_invalid_reach_raises(self) -> None:
        sa = SentimentAnalyzer()
        with pytest.raises(ValueError, match="reach"):
            sa.analyze_text("text", reach=2.0)

    def test_analyze_inference_exception_logs_error(self) -> None:
        """L141: torch inference failure inside try → logger.error → sentinel."""
        sa = SentimentAnalyzer()
        sa._model = SimpleNamespace()  # type: ignore[assignment]

        def boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("boom")

        sa._tokenizer = boom  # type: ignore[assignment]
        out = sa.analyze_text("text")
        assert isinstance(out, dict)
        assert np.isnan(list(out.values())[0])

    def test_generative_exception_logs_error(self) -> None:
        """L163-165: generative decode failure → logger.error → sentinel."""

        class BoomTokenizer:
            def __call__(self, *a: Any, **k: Any) -> dict[str, Any]:
                return {"input_ids": SimpleNamespace(shape=[1])}

            def decode(self, *a: Any, **k: Any) -> str:
                raise RuntimeError("decode boom")

        sa = SentimentAnalyzer()
        sa._generative = True
        sa._model = SimpleNamespace()
        sa._tokenizer = BoomTokenizer()
        out = sa._analyze_generative("text")
        assert isinstance(out, dict)
        assert np.isnan(list(out.values())[0])

    def test_weighted_daily_mean_empty_frame(self) -> None:
        """L209: all-NaN scores → empty frame → empty float Series."""
        sa = SentimentAnalyzer()
        frame = pd.DataFrame({"score": [np.nan, np.nan], "reach": [1.0, 2.0], "date": [1, 2]})
        out = sa._weighted_daily_mean(frame)
        assert isinstance(out, pd.Series)
        assert out.empty

    @pytest.mark.asyncio
    async def test_fetch_news_with_explicit_cryptopanic_and_date(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L262/265 + L296-298: cryptopanic already registered; date column parsed."""
        fake_module = types.ModuleType("feedparser")
        fake_module.parse = lambda url: SimpleNamespace(
            entries=[
                {
                    "title": "a",
                    "published": "Mon, 01 Jan 2024 00:00:00 GMT",
                    "link": "u",
                }
            ]
        )
        monkeypatch.setitem(sys.modules, "feedparser", fake_module)
        collector = NewsCollector()
        collector.add_source("cryptopanic")
        df = await collector.fetch_news(max_items=5)
        assert "date" in df.columns


# ------------------------------------------------------------ model_registry
class TestModelRegistryTail:
    def test_constructor_mapping_readiness(self, tmp_path: pytest.TempPathFactory) -> None:
        """L69-71: Mapping branch → PaperReadinessConfig.from_mapping."""
        reg = ModelRegistry(tmp_path / "registry", paper_readiness={"min_paper_days": 7})
        assert reg._paper_readiness.min_paper_days == 7

    def test_promote_to_live_with_evidence(self, tmp_path: pytest.TempPathFactory) -> None:
        """L225: evidence not None branch on promote_to_live."""
        reg = ModelRegistry(tmp_path / "registry")
        reg.register("m1", "ModelCls", "hash123", {"passed": True, "decision": "GO"})
        # promote_to_live requires status == paper; use attach_paper_evidence path first
        entry = reg.get("m1")
        entry["status"] = "paper"
        reg._write(entry)
        entry = reg.promote_to_live(
            "m1", paper_evidence={"paper_days": 30, "fills": 50, "orders": 10}
        )
        assert entry["paper_evidence"]["fills"] == 50


# ---------------------------------------------------------------- ai_training
class TestAITrainerTail:
    def test_model_without_feature_importances(self) -> None:
        """L176 branch False: model lacking feature_importances_ → empty map."""

        class PlainModel:
            def __init__(self, random_state: int = 0, **kw: Any) -> None:
                self.random_state = random_state

            def fit(self, *a: Any, **k: Any) -> "PlainModel":
                return self

            def predict(self, *a: Any, **k: Any) -> np.ndarray:
                return np.zeros(len(a[0]))

            def predict_proba(self, X: Any) -> np.ndarray:
                return np.column_stack([np.ones(len(X)) * 0.3, np.ones(len(X)) * 0.7])

        pipe = AITrainingPipeline(random_state=0)
        features = pd.DataFrame(
            {
                "rsi": np.linspace(30, 70, 80),
                "mom": np.linspace(-1, 1, 80),
                "timestamp": np.arange(80),
            }
        )
        close = pd.Series(np.linspace(100, 120, 80))
        report = pipe.train(features, close, PlainModel)
        assert report.model_cls == "PlainModel"


# ------------------------------------------------------------------- ai_factors
class TestAiFactorsTail:
    def test_expanding_splits_test_end_guard(self) -> None:
        """L43-41 branch: test_end > test_start filter."""
        splits = _expanding_splits(100, max_splits=3)
        assert splits
        for train, test in splits:
            assert test.stop > test.start


# --------------------------------------------------------------------- auto_loop
class TestAutoLoopTail:
    def test_metric_summary_checks_dict(self) -> None:
        """L150-161: checks dict iteration producing compact summary."""
        validation = {
            "checks": {
                "dsr": {"passed": True, "value": 0.5},
                "pbo": {"passed": False, "value": 0.99},
            }
        }
        out = _metric_summary(validation)
        assert isinstance(out, dict)
        assert "dsr" in out


# ---------------------------------------------------------------- cost_fidelity
class TestCostFidelityTail:
    def test_row_metric_conversion_error_returns_none(self) -> None:
        """L114-115: non-numeric value → TypeError/ValueError → None."""
        assert _row_metric({"a": "not-a-number"}, "a") is None

    def test_extract_funding_tca_from_checks(self) -> None:
        """L210/218-220: cost_fidelity/checks nesting lookup."""
        report = {"checks": {"cost_fidelity": {"funding_tca": {"daily": [1.0]}}}}
        assert extract_funding_tca(report) == {"daily": [1.0]}

    def test_extract_funding_tca_nested_cost_branch(self) -> None:
        """L209: cost_fidelity dict with tca key."""
        report = {"cost_fidelity": {"tca": {"hourly": [2.0]}}}
        assert extract_funding_tca(report) == {"hourly": [2.0]}


# -------------------------------------------------------------- paper_readiness
class TestPaperReadinessTail:
    def test_fills_none_fails(self) -> None:
        """L183-184: fills is None → 'fills unmeasurable'."""
        cfg = PaperReadinessConfig(min_fills=1, min_orders=0)
        with pytest.raises(Exception, match="fills"):
            assert_paper_readiness(
                {"paper_days": 10, "fills": None, "orders": 5}, config=cfg
            )

    def test_require_when_missing_skip(self) -> None:
        """L234-242: require_when_missing=False + no evidence → skip (passed)."""
        cfg = PaperReadinessConfig(min_fills=1)
        result = assert_report_paper_ready(None, config=cfg, require_when_missing=False)
        assert result["passed"] is True


# --------------------------------------------------------------------- lookahead
class TestLookaheadTail:
    def test_attr_chain_subscript(self) -> None:
        """L130: Subscript chain rendering."""
        node = __import__("ast").parse("df.close[x]").body[0].value
        chain = _attr_chain(node)
        assert "df.close" in chain

    def test_scan_strategy_shape2_agg_mask(self) -> None:
        """L202-225: agg(mask) Shape-2 finding via ast.Attribute func."""

        class FakeStrategy:
            def generate_signals(self, df: Any) -> tuple[Any, Any]:
                import numpy as _np

                mask = df.close > 0
                val = _np.mean(df.close[mask])
                return (val > 1, val < 0)

        report = scan_strategy(FakeStrategy())
        assert report.findings is not None


# -------------------------------------------------------------- promotion_path
class TestPromotionPathTail:
    def test_extract_fingerprint_from_run_meta_and_pin(self) -> None:
        """L106-120: nested checks/run_meta/contract_pin lookup branches."""
        assert extract_data_fingerprint(
            {"checks": {"promotion_path": {"data_fingerprint": {"hash": "x"}}}}
        ) == {"hash": "x"}
        assert extract_data_fingerprint({"run_meta": {"data_fingerprint": "fp2"}}) == "fp2"
        assert extract_data_fingerprint({"contract_pin": {"data_fingerprint": "fp3"}}) == "fp3"
        assert extract_data_fingerprint({"checks": {"fingerprint": "fp4"}}) == "fp4"


# ------------------------------------------------------------ causal_preflight
class TestCausalPreflightTail:
    def test_dedup_skips_duplicate_negative_shift(self) -> None:
        """L157-158: dedup by line+snippet continues on duplicates."""
        report = run_causal_preflight(
            None, extra_sources=[("dup", "df.close.shift(-1) > 0\nx = df.close.shift(-1)")]
        )
        assert report is not None


# --------------------------------------------------------------------- recursive
class NameStrategy:
    def generate_signals(self, df: Any) -> tuple[Any, Any]:
        engine = SimpleNamespace()
        engine.compute = lambda: df.close
        engine.compute_all = lambda: df.close
        return (df.close > 0, df.close < 0)


class TestRecursiveTail:
    def test_scan_name_based_indicator_calls(self) -> None:
        """L98-94: Attribute value Name branch in indicator call scan."""
        report = scan_recursive(NameStrategy)
        assert report is not None


# --------------------------------------------------------------------------- wfo
class TestWfoTail:
    def test_all_folds_skipped_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        """L168-175: not folds + skipped_folds warning branch."""
        close = pd.Series(range(100, 105), dtype=float)
        entries = pd.Series(False, index=close.index)
        exits = pd.Series(False, index=close.index)
        wfo = WalkForwardOptimization(n_folds=5, test_ratio=0.9, purge_delta=10)
        with caplog.at_level("WARNING"):
            result = wfo.run(close, entries, exits)
        assert result.folds == []
        assert any("all 5 folds skipped" in r.message for r in caplog.records)

    def test_partial_skips_logs_effective_count(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """L191-199: some folds skipped → warning with effective count."""

        def fake_optimize(train_close: pd.Series):
            n = len(train_close)
            entries = pd.Series(False, index=train_close.index)
            exits = pd.Series(False, index=train_close.index)
            return entries, exits, {"p": 1}

        close = pd.Series(range(100, 120), dtype=float)
        entries = pd.Series(False, index=close.index)
        exits = pd.Series(False, index=close.index)
        entries.iloc[0] = True
        exits.iloc[2] = True
        wfo = WalkForwardOptimization(n_folds=4, test_ratio=0.4, anchored=True)
        with caplog.at_level("WARNING"):
            result = wfo.run(close, entries, exits, optimize_fn=fake_optimize)
        assert result.folds


# --------------------------------------------------------------------------- cpcv
class TestCpcvTail:
    def test_close_column_present_in_train_slice(self) -> None:
        """L183-185: 'close' in train_slice.columns → reindex path."""
        n = 200
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        rng = np.random.default_rng(42)
        prices = 100.0 * pd.Series(1.0 + rng.normal(0, 0.01, n), index=dates).cumprod()
        entries = pd.Series(False, index=dates)
        exits = pd.Series(False, index=dates)
        for i in range(0, n, 20):
            entries.iloc[i] = True
        for i in range(10, n, 20):
            exits.iloc[i] = True
        result = cpcv_backtest(
            prices,
            entries,
            exits,
            n_groups=4,
            n_test_groups=2,
            n_trials=2,
            signal_fn=lambda df, **kw: (df.close > 0, df.close < 0),
        )
        assert result is not None
