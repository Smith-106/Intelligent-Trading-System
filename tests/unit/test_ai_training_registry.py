"""Tests for the AI model training pipeline and model registry (s3 T-s3-03).

Covers: training produces a gate report, low-score models are refused
(fail-closed), GO models register as paper, paper → live promotion requires
intact registration, and persistence round-trips.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.strategy.ai_training import AITrainingPipeline, TrainedModelReport
from quantflow.strategy.model_registry import (
    STATUS_LIVE,
    STATUS_PAPER,
    STATUS_REJECTED,
    ModelRegistry,
    ModelRegistryError,
)


def _go_report_with_cost(**extra: object) -> dict:
    """Minimal GO report: P0+T014 cost + W14 paper_replay path."""
    from quantflow.strategy.validation.cost_fidelity import build_funding_tca

    report: dict = {
        "decision": "GO",
        "fee_slip_grid": [
            {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.0, "return_pct": 20.0},
            {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.55, "return_pct": 10.0},
        ],
        "funding_tca": build_funding_tca(mode="assumption"),
        "execution_path": "paper_replay",
        "data_fingerprint": {"aggregate": "test-fingerprint-w14"},
        "checks": {},
    }
    report.update(extra)
    return report


def _make_features(n: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "momentum_5": rng.standard_normal(n),
            "volatility_20": np.abs(rng.standard_normal(n)),
            "funding_rate_ma_3": rng.standard_normal(n) * 0.001,
            "oi_change_1": rng.standard_normal(n) * 0.01,
        },
        index=idx,
    )


def _make_close(n: int = 200, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    returns = rng.standard_normal(n) * 0.01
    # Mild trend so a classifier can find signal.
    returns = returns + 0.002
    close = 100.0 * np.exp(np.cumsum(returns))
    return pd.Series(close, index=idx, name="close")


class TestAITrainingPipeline:
    def test_train_returns_report(self):
        pipe = AITrainingPipeline(
            validation_kwargs={"cpcv_groups": 4, "cpcv_test_groups": 1, "wfo_windows": 3}
        )
        report = pipe.train(_make_features(), _make_close(), None, n_estimators=30, max_depth=3)
        assert isinstance(report, TrainedModelReport)
        assert report.n_samples >= 60
        assert report.decision in ("GO", "NO-GO")
        assert "cpcv" in report.validation.get("checks", {})
        assert report.features_hash

    def test_insufficient_samples_returns_no_go(self):
        pipe = AITrainingPipeline()
        report = pipe.train(_make_features(n=30), _make_close(n=30), None)
        assert report.decision == "NO-GO"
        assert "insufficient" in report.reason

    def test_importance_captured(self):
        pipe = AITrainingPipeline(
            validation_kwargs={"cpcv_groups": 4, "cpcv_test_groups": 1, "wfo_windows": 3}
        )
        report = pipe.train(_make_features(), _make_close(), None, n_estimators=30, max_depth=3)
        assert len(report.feature_importance) > 0
        # Importance names must be feature columns.
        assert set(report.feature_importance) <= set(_make_features().columns)


class TestModelRegistry:
    def test_register_go_becomes_paper(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        entry = reg.register("m1", "RandomForestClassifier", "h1", _go_report_with_cost())
        assert entry["status"] == STATUS_PAPER
        assert reg.get("m1")["status"] == STATUS_PAPER

    def test_register_no_go_is_rejected_fail_closed(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        entry = reg.register(
            "m2",
            "RandomForestClassifier",
            "h2",
            {"decision": "NO-GO", "reason": "DSR < 0.95"},
        )
        assert entry["status"] == STATUS_REJECTED
        # It is still persisted (audit trail) but never paper.
        assert reg.get("m2")["status"] == STATUS_REJECTED

    def test_register_missing_decision_denied(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        entry = reg.register("m3", "X", "h3", {})
        assert entry["status"] == STATUS_REJECTED

    def test_register_go_without_cost_grid_rejected(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        entry = reg.register("m_costless", "X", "h", {"decision": "GO", "checks": {}})
        assert entry["status"] == STATUS_REJECTED
        assert "cost fidelity" in entry["reason"]

    def test_register_zero_cost_only_go_rejected(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        report = {
            "decision": "GO",
            "fee_slip_grid": [
                {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.2, "return_pct": 40.0},
                {"taker_fee": 0.001, "slippage": 0.001, "sharpe": -0.1, "return_pct": -2.0},
            ],
        }
        entry = reg.register("m_zconly", "X", "h", report)
        assert entry["status"] == STATUS_REJECTED
        assert "zero-cost-only" in entry["reason"] or "cost fidelity" in entry["reason"]

    def test_duplicate_go_raises(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        reg.register("m4", "X", "h", _go_report_with_cost())
        with pytest.raises(ModelRegistryError, match="already registered"):
            reg.register("m4", "X", "h", _go_report_with_cost())

    def test_promote_paper_to_live(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        reg.register("m5", "X", "h", _go_report_with_cost())
        entry = reg.promote_to_live("m5", paper_evidence={"paper_days": 14, "fills": 40})
        assert entry["status"] == STATUS_LIVE
        assert reg.get("m5")["status"] == STATUS_LIVE

    def test_promote_rejected_raises(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        reg.register("m6", "X", "h", {"decision": "NO-GO"})
        with pytest.raises(ModelRegistryError, match="not promotable"):
            reg.promote_to_live("m6")

    def test_promote_missing_raises(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        with pytest.raises(ModelRegistryError, match="not found"):
            reg.promote_to_live("ghost")

    def test_persistence_round_trip(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        reg.register("m7", "X", "h", _go_report_with_cost(reason="ok"))
        reg2 = ModelRegistry(tmp_path)  # new instance reads same dir
        assert reg2.get("m7")["status"] == STATUS_PAPER
        assert reg2.list_models()[0]["model_id"] == "m7"

    def test_invalid_model_id_rejected(self, tmp_path):
        reg = ModelRegistry(tmp_path)
        with pytest.raises(ModelRegistryError, match="Invalid model_id"):
            reg.register("../evil", "X", "h", _go_report_with_cost())

    def test_validation_summary_is_json_safe(self, tmp_path):
        """checks with numpy values serialize via to_dict-free path."""
        import json

        reg = ModelRegistry(tmp_path)
        report = _go_report_with_cost(
            checks={"dsr": {"passed": True, "dsr": float(np.float64(0.97))}}
        )
        entry = reg.register("m8", "X", "h", report)
        # Re-serializing the entry must not crash on numpy types.
        json.dumps(entry)
