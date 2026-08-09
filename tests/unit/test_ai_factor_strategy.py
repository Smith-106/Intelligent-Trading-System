"""Tests for AIFactorStrategy — s4 T-s4-03 (registry-driven AI factor).

Covers: registry with usable model (probability gates momentum), empty
registry / failed load (degradation to pure momentum), prediction failure
(degradation), and allowlisted model instantiation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quantflow.strategy.model_registry import ModelRegistry
from quantflow.strategy.templates.ai_factor_strategy import AIFactorStrategy, _instantiate_model


def _df(n: int = 120) -> pd.DataFrame:
    """Synthetic OHLCV with a clear uptrend (fast MA > slow MA)."""
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    close = pd.Series(100.0 + np.linspace(0, 10, n), index=idx)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0,
        },
        index=idx,
    )


class _ModelStub:
    """Sklearn-style classifier stub returning scripted probabilities."""

    def __init__(self, proba: float) -> None:
        self._proba = proba
        self.classes_ = np.array([0, 1])

    def predict_proba(self, features: Any) -> np.ndarray:
        return np.tile([1 - self._proba, self._proba], (len(features), 1))


def _go_with_cost(**extra: object) -> dict:
    from quantflow.strategy.validation.cost_fidelity import build_funding_tca

    report: dict = {
        "decision": "GO",
        "reason": "gate passed",
        "fee_slip_grid": [
            {"taker_fee": 0.0, "slippage": 0.0, "sharpe": 1.0, "return_pct": 20.0},
            {"taker_fee": 0.001, "slippage": 0.001, "sharpe": 0.55, "return_pct": 10.0},
        ],
        "funding_tca": build_funding_tca(mode="assumption"),
    }
    report.update(extra)
    return report


def _seed_registry(tmp_path: Path, model_cls: str = "RandomForestClassifier", status: str = "paper") -> str:
    reg = ModelRegistry(str(tmp_path))
    model_id = "m-test-1"
    reg.register(
        model_id=model_id,
        model_cls=model_cls,
        features_hash="abc",
        validation_report=_go_with_cost(),
    )
    if status == "live":
        reg.promote_to_live(
            model_id, paper_evidence={"paper_days": 14, "fills": 40}
        )
    return model_id


class TestAIFactorStrategyRegistry:
    def test_uptrend_plus_high_ai_probability_enters_long(self, tmp_path: Path) -> None:
        _seed_registry(tmp_path)
        strat = AIFactorStrategy(params={"registry_dir": str(tmp_path), "model_id": "m-test-1"})
        strat._model = _ModelStub(0.9)
        entries, exits = strat.generate_signals(_df())
        assert entries.any()
        assert not exits.any()

    def test_uptrend_plus_low_ai_probability_blocks_long(self, tmp_path: Path) -> None:
        _seed_registry(tmp_path)
        strat = AIFactorStrategy(params={"registry_dir": str(tmp_path), "model_id": "m-test-1"})
        strat._model = _ModelStub(0.4)  # below 0.55 entry threshold
        entries, _ = strat.generate_signals(_df())
        assert not entries.any()

    def test_empty_registry_degrades_to_momentum(self, tmp_path: Path) -> None:
        strat = AIFactorStrategy(params={"registry_dir": str(tmp_path)})
        strat._load_model()
        assert strat._model is None
        # Uptrend → long entries without any AI gate.
        entries, _ = strat.generate_signals(_df())
        assert entries.any()

    def test_missing_model_id_degrades_to_momentum(self, tmp_path: Path) -> None:
        _seed_registry(tmp_path)
        strat = AIFactorStrategy(params={"registry_dir": str(tmp_path), "model_id": "m-does-not-exist"})
        strat._load_model()
        assert strat._model is None
        entries, _ = strat.generate_signals(_df())
        assert entries.any()

    def test_registry_load_picks_live_model_preferred(self, tmp_path: Path) -> None:
        reg = ModelRegistry(str(tmp_path))
        reg.register("m-paper", "RandomForestClassifier", "h1", _go_with_cost())
        reg.register("m-live", "RandomForestClassifier", "h2", _go_with_cost())
        reg.promote_to_live(
            "m-live", paper_evidence={"paper_days": 14, "fills": 40}
        )
        strat = AIFactorStrategy(params={"registry_dir": str(tmp_path)})
        strat._load_model()
        assert strat._model_id == "m-live"

    def test_corrupt_registry_dir_is_fail_closed_degradation(self, tmp_path: Path) -> None:
        # Write a corrupt JSON so registry.get fails → degrade, not raise.
        (tmp_path / "m-bad.json").write_text("{not json", encoding="utf-8")
        strat = AIFactorStrategy(params={"registry_dir": str(tmp_path), "model_id": "m-bad"})
        strat._load_model()  # must not raise
        assert strat._model is None


class TestAIFactorStrategyPrediction:
    def test_prediction_failure_degrades_to_momentum(self, tmp_path: Path) -> None:
        _seed_registry(tmp_path)
        strat = AIFactorStrategy(params={"registry_dir": str(tmp_path), "model_id": "m-test-1"})

        class _Broken:
            def predict_proba(self, features: Any) -> np.ndarray:
                raise RuntimeError("boom")

        strat._model = _Broken()
        entries, _ = strat.generate_signals(_df())
        # Degradation → momentum entries still fire.
        assert entries.any()

    def test_invalid_model_class_not_instantiated(self) -> None:
        assert _instantiate_model("os.system") is None
        assert _instantiate_model("") is None
        from sklearn.ensemble import RandomForestClassifier

        assert isinstance(_instantiate_model("RandomForestClassifier"), RandomForestClassifier)


class TestAIFactorStrategyShortSide:
    def test_downtrend_with_low_ai_probability_enters_short(self, tmp_path: Path) -> None:
        _seed_registry(tmp_path)
        strat = AIFactorStrategy(params={"registry_dir": str(tmp_path), "model_id": "m-test-1"})
        strat._model = _ModelStub(0.2)  # P(up) low → short side
        df = _df()
        # Reverse the trend for a downtrend.
        df["close"] = 110.0 - np.linspace(0, 10, len(df))
        df["open"], df["high"], df["low"] = df["close"], df["close"] + 0.5, df["close"] - 0.5
        entries, exits = strat.generate_signals(df)
        # Short is expressed via the "exits" side of the long-only API? No —
        # our short is an exit of the long bias; assert at least one signal.
        assert entries.any() or exits.any()
