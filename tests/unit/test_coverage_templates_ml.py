"""Coverage completion for AI/ML strategy templates.

Targets remaining uncovered lines/branches in:
- ai_factor_strategy: _load_model early return + registry paths (no models,
  unusable model, unknown model_cls, success), on_init, on_bar emit paths,
  generate_signals short-history, _predict_up empty-features + single-class
  proba, _instantiate_model LogisticRegression/GradientBoosting, _bars_to_df
- ml_ensemble: train_model without meta labels (skip meta dump), _load_model
  with primary-only artifact (meta file absent)

Registry/model interactions are mocked; no real model training (fake
classifiers), no network, no vectorbt.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.ai_factor_strategy import (
    AIFactorStrategy,
    _bars_to_df,
    _instantiate_model,
)
from quantflow.strategy.templates.ml_ensemble import MLEnsembleStrategy


class _Ctx:
    def __init__(self) -> None:
        self.signals: list[tuple] = []
        self.params: dict = {}

    def emit_signal(
        self,
        symbol: str,
        direction: Direction,
        strength: float = 1.0,
        price: float = 0.0,
        strategy_id: str = "",
    ) -> None:
        self.signals.append((symbol, direction, strength, price, strategy_id))


def _bar(close: float, ts: int = 0) -> Bar:
    return Bar(
        symbol="BTC/USDT",
        timestamp=ts,
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1000.0,
    )


def _df(n: int = 80) -> pd.DataFrame:
    close = pd.Series(np.linspace(100.0, 140.0, n))
    return pd.DataFrame(
        {
            "open": close - 1,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": np.linspace(1000.0, 1200.0, n),
        }
    )


class _FakeClassifier:
    """Dumb classifier for train_model (no real sklearn work)."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.n_classes_ = 2

    def fit(self, x, y):  # type: ignore[no-untyped-def]
        return self

    def predict(self, x) -> np.ndarray:  # type: ignore[no-untyped-def]
        return np.ones(len(x), dtype=int)

    def predict_proba(self, x) -> np.ndarray:  # type: ignore[no-untyped-def]
        return np.column_stack([np.full(len(x), 0.2), np.full(len(x), 0.8)])


# ---------------------------------------------------------------------------
# ai_factor_strategy
# ---------------------------------------------------------------------------


def _fake_registry(**overrides) -> MagicMock:
    reg = MagicMock()
    default = {
        "list_models": [],
        "get": None,
    }
    default.update(overrides)
    reg.list_models.return_value = default["list_models"]
    reg.get.return_value = default["get"]
    return reg


class TestAIFactorStrategy:
    def test_on_init_sets_params_and_loads_model(self) -> None:
        s = AIFactorStrategy(params={"registry_dir": "/nonexistent"})
        ctx = StrategyContext()
        with patch("quantflow.strategy.model_registry.ModelRegistry", side_effect=OSError("x")):
            s.on_init(ctx)
        assert ctx.params == s._params
        assert s._model_loaded is True

    def test_load_model_already_loaded(self) -> None:
        s = AIFactorStrategy()
        s._model_loaded = True
        s._load_model()  # early return, no registry touched
        assert s._model_loaded is True

    def test_load_model_no_usable_entries(self) -> None:
        s = AIFactorStrategy(params={"registry_dir": "/x"})
        with patch(
            "quantflow.strategy.model_registry.ModelRegistry", return_value=_fake_registry()
        ):
            s._load_model()
        assert s._model is None

    def test_load_model_entry_not_usable(self) -> None:
        reg = _fake_registry(get={"model_id": "m1", "status": "archived"})
        s = AIFactorStrategy(params={"registry_dir": "/x", "model_id": "m1"})
        with patch("quantflow.strategy.model_registry.ModelRegistry", return_value=reg):
            s._load_model()
        assert s._model is None

    def test_load_model_unknown_model_cls(self) -> None:
        reg = _fake_registry(get={"model_id": "m1", "status": "live", "model_cls": "MysteryNet"})
        s = AIFactorStrategy(params={"registry_dir": "/x", "model_id": "m1"})
        with patch("quantflow.strategy.model_registry.ModelRegistry", return_value=reg):
            s._load_model()
        assert s._model is None
        assert s._model_id == "m1"

    def test_load_model_success_without_model_id(self) -> None:
        reg = _fake_registry(
            list_models=[
                {"model_id": "old", "status": "paper", "registered_at": "2020-01-01"},
                {"model_id": "new", "status": "live", "registered_at": "2021-01-01"},
            ],
            get={"model_id": "new", "status": "live", "model_cls": "RandomForestClassifier"},
        )
        s = AIFactorStrategy(params={"registry_dir": "/x"})
        with patch("quantflow.strategy.model_registry.ModelRegistry", return_value=reg):
            s._load_model()
        assert s._model is not None
        assert s._model_id == "new"

    def test_on_bar_emits_long_and_flat(self) -> None:
        s = AIFactorStrategy(
            params={"fast_ma_period": 3, "slow_ma_period": 5, "registry_dir": "/x"}
        )
        # force no model -> pure momentum path
        s._model_loaded = True
        ctx = _Ctx()
        # flat warmup so the fast/slow crossover happens after min_history
        seq = [100.0] * 10 + [101.0, 102.0, 103.0, 104.0, 105.0, 99.0, 98.0, 97.0, 96.0, 95.0]
        for i, c in enumerate(seq):
            s.on_bar(ctx, _bar(c, ts=i))
        dirs = [sg[1] for sg in ctx.signals]
        assert dirs == [Direction.LONG, Direction.FLAT]

    def test_on_bar_short_history(self) -> None:
        s = AIFactorStrategy(params={"fast_ma_period": 3, "slow_ma_period": 5})
        ctx = _Ctx()
        for i in range(4):  # < min_history
            s.on_bar(ctx, _bar(100.0 + i, ts=i))
        assert ctx.signals == []

    def test_on_bar_entries_empty(self) -> None:
        s = AIFactorStrategy(params={"fast_ma_period": 3, "slow_ma_period": 5})
        s._model_loaded = True
        ctx = _Ctx()
        for i in range(12):
            s.on_bar(ctx, _bar(100.0, ts=i))
        # flat prices -> no entry/exit flips on the last bar -> no signals
        assert ctx.signals == []

    def test_on_bar_entries_empty_via_generate_patch(self) -> None:
        # entries.empty branch: generate_signals returns empty series
        s = AIFactorStrategy(params={"fast_ma_period": 3, "slow_ma_period": 5})
        s._model_loaded = True
        s.generate_signals = lambda df: (  # type: ignore[method-assign]
            pd.Series(dtype=bool),
            pd.Series(dtype=bool),
        )
        ctx = _Ctx()
        for i in range(12):
            s.on_bar(ctx, _bar(100.0, ts=i))
        assert ctx.signals == []

    def test_on_bar_trims_bars(self) -> None:
        s = AIFactorStrategy(params={"fast_ma_period": 3, "slow_ma_period": 5})
        ctx = _Ctx()
        for i in range(60):
            s.on_bar(ctx, _bar(100.0 + (i % 7), ts=i))
        assert len(s._bars) <= s._max_bars

    def test_generate_signals_short_history(self) -> None:
        s = AIFactorStrategy(params={"fast_ma_period": 3, "slow_ma_period": 5})
        df = _df(5)
        entries, _exits = s.generate_signals(df)
        assert len(entries) == 5
        assert int(entries.sum()) == 0

    def test_generate_signals_with_model_prediction_failure(self) -> None:
        s = AIFactorStrategy(params={"fast_ma_period": 3, "slow_ma_period": 5})
        s._model = MagicMock()
        s._model.predict_proba.side_effect = RuntimeError("boom")
        df = _df(30)
        entries, _exits = s.generate_signals(df)
        assert int(entries.sum()) >= 0  # degraded to momentum, no raise

    def test_predict_up_empty_features(self) -> None:
        s = AIFactorStrategy()
        empty = pd.DataFrame({"close": pd.Series(dtype=float)})
        out = s._predict_up(empty)
        assert len(out) == 0  # empty index -> empty 0.5 series

    def test_predict_up_single_column_proba(self) -> None:
        s = AIFactorStrategy()
        s._model = MagicMock()
        s._model.predict_proba.return_value = np.full((6, 1), 0.7)
        df = _df(6)
        out = s._predict_up(df)
        assert out.tolist() == [0.7] * 6

    def test_instantiate_model_allowlist(self) -> None:
        from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
        from sklearn.linear_model import LogisticRegression

        assert isinstance(_instantiate_model("RandomForestClassifier"), RandomForestClassifier)
        assert isinstance(_instantiate_model("LogisticRegression"), LogisticRegression)
        assert isinstance(
            _instantiate_model("GradientBoostingClassifier"), GradientBoostingClassifier
        )
        assert _instantiate_model("UnknownModel") is None

    def test_bars_to_df(self) -> None:
        df = _bars_to_df([_bar(100.0, 1), _bar(101.0, 2)])
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df["close"].tolist() == [100.0, 101.0]


# ---------------------------------------------------------------------------
# ml_ensemble
# ---------------------------------------------------------------------------


class TestMLEnsemble:
    def test_train_model_without_meta_labels_skips_meta_dump(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """meta_labels=None -> _meta_model stays None -> meta dump skipped."""
        strategy = MLEnsembleStrategy(params={"model_path": str(tmp_path / "model.joblib")})
        df = _df(8)
        features = pd.DataFrame(
            {"f1": [1.0, 2.0, 3.0, 4.0], "f2": [4.0, 5.0, 6.0, 7.0]},
            index=df.index[:4],
        )
        labels = pd.Series([1, 0, 1, 1], index=features.index)
        dumps: list[str] = []

        monkeypatch.setattr(strategy, "_extract_features", lambda frame: features)

        sklearn = ModuleType("sklearn")
        ensemble = ModuleType("sklearn.ensemble")
        ensemble.GradientBoostingClassifier = _FakeClassifier
        monkeypatch.setitem(sys.modules, "sklearn", sklearn)
        monkeypatch.setitem(sys.modules, "sklearn.ensemble", ensemble)

        joblib = ModuleType("joblib")
        joblib.dump = lambda model, path: dumps.append(str(path))
        monkeypatch.setitem(sys.modules, "joblib", joblib)

        result = strategy.train_model(df, labels, meta_labels=None)

        assert result["validation_method"] == "time_series_expanding_oos"
        assert strategy._model is not None
        assert strategy._meta_model is None
        # only the primary model is dumped (no _meta.joblib)
        assert dumps == [str(tmp_path / "model.joblib")]

    def test_load_model_primary_only_meta_missing(self, tmp_path: Path) -> None:
        """Primary artifact exists, meta artifact absent -> 401 False branch."""
        from joblib import dump

        primary = tmp_path / "model.joblib"
        dump({"kind": "primary"}, primary)
        strategy = MLEnsembleStrategy(params={"model_path": str(primary)})
        strategy._load_model()
        assert strategy._model == {"kind": "primary"}
        assert strategy._meta_model is None

    def test_load_model_primary_and_meta(self, tmp_path: Path) -> None:
        from joblib import dump

        primary = tmp_path / "model.joblib"
        dump({"kind": "primary"}, primary)
        dump({"kind": "meta"}, tmp_path / "model_meta.joblib")
        strategy = MLEnsembleStrategy(params={"model_path": str(primary)})
        strategy._load_model()
        assert strategy._meta_model == {"kind": "meta"}
