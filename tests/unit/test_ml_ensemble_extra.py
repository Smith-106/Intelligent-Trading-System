"""Additional branch coverage tests for the ML ensemble strategy."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyContext
from quantflow.strategy.templates.ml_ensemble import MLEnsembleStrategy


def _make_df(n: int = 80) -> pd.DataFrame:
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


def _make_bar(ts: int, close: float = 100.0, symbol: str = "BTC/USDT") -> Bar:
    return Bar(
        symbol=symbol,
        timestamp=ts,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=10.0,
    )


class _FakeClassifier:
    def __init__(self, *args, **kwargs) -> None:
        self.fit_calls: list[tuple[pd.DataFrame, pd.Series]] = []
        self.n_classes_ = 2

    def fit(self, x: pd.DataFrame, y: pd.Series) -> _FakeClassifier:
        self.fit_calls.append((x.copy(), y.copy()))
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.ones(len(x), dtype=int)

    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        return np.column_stack([np.full(len(x), 0.2), np.full(len(x), 0.8)])


class _OneClassModel:
    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        return np.ones((len(x), 1)) * 0.75


class _BrokenModel:
    def predict_proba(self, x: pd.DataFrame) -> np.ndarray:
        raise RuntimeError("predict failed")


class _BrokenMetaModel:
    def predict(self, x: pd.DataFrame) -> np.ndarray:
        raise RuntimeError("meta failed")


class TestMLEnsembleExtra:
    def test_on_bar_trims_history_and_emits_long_or_flat_signals(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = MLEnsembleStrategy(params={"lookback": 3})
        strategy._model = object()
        strategy._max_bars = 4
        ctx = StrategyContext()

        monkeypatch.setattr(strategy, "_bars_to_df", lambda: _make_df(4))
        signal_sets = [
            (
                pd.Series([False, False, False, True]),
                pd.Series([False, False, False, False]),
            ),
            (
                pd.Series([False, False, False, False]),
                pd.Series([False, False, False, True]),
            ),
            (
                pd.Series([False, False, False, False]),
                pd.Series([False, False, False, False]),
            ),
        ]
        call_index = {"value": 0}

        def _generate(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
            idx = min(call_index["value"], len(signal_sets) - 1)
            call_index["value"] += 1
            return signal_sets[idx]

        monkeypatch.setattr(strategy, "generate_signals", _generate)

        for ts in range(5):
            strategy.on_bar(ctx, _make_bar(ts, close=100 + ts))

        signals = ctx.flush_signals()

        assert len(strategy._bars) == 4
        assert len(signals) == 2
        assert signals[0].direction == Direction.LONG
        assert signals[1].direction == Direction.FLAT

    def test_on_bar_returns_when_dataframe_or_entries_are_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = MLEnsembleStrategy(params={"lookback": 2})
        strategy._model = object()
        ctx = StrategyContext()

        monkeypatch.setattr(strategy, "_bars_to_df", lambda: pd.DataFrame())
        strategy.on_bar(ctx, _make_bar(1))
        assert ctx.flush_signals() == []

        monkeypatch.setattr(strategy, "_bars_to_df", lambda: _make_df(3))
        monkeypatch.setattr(
            strategy,
            "generate_signals",
            lambda df: (pd.Series(dtype=bool), pd.Series(dtype=bool)),
        )
        strategy.on_bar(ctx, _make_bar(2))
        assert ctx.flush_signals() == []

    def test_on_bar_returns_when_dataframe_is_empty_after_lookback_is_satisfied(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = MLEnsembleStrategy(params={"lookback": 2})
        strategy._model = object()
        strategy._bars = [_make_bar(0)]
        ctx = StrategyContext()

        monkeypatch.setattr(strategy, "_bars_to_df", lambda: pd.DataFrame())
        strategy.on_bar(ctx, _make_bar(1))

        assert ctx.flush_signals() == []

    def test_on_bar_returns_before_signal_generation_when_model_missing_or_lookback_shortfall(
        self,
    ) -> None:
        strategy = MLEnsembleStrategy(params={"lookback": 3})
        ctx = StrategyContext()

        strategy.on_bar(ctx, _make_bar(1))
        strategy._model = object()
        strategy.on_bar(ctx, _make_bar(2))

        assert ctx.flush_signals() == []

    def test_generate_signals_handles_single_class_and_prediction_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = MLEnsembleStrategy(
            params={"lookback": 5, "entry_threshold": 0.7, "exit_threshold": 0.4}
        )
        df = _make_df(20)
        features = pd.DataFrame({"f1": [1.0, 2.0, 3.0]}, index=df.index[-3:])

        strategy._model = _OneClassModel()
        monkeypatch.setattr(strategy, "_extract_features", lambda frame: features)
        monkeypatch.setattr(
            strategy,
            "_apply_meta_labeling",
            lambda frame, proba: pd.Series([True, False, True], index=proba.index),
        )

        entries, exits = strategy.generate_signals(df)

        assert list(entries.loc[features.index]) == [True, False, True]
        assert list(exits.loc[features.index]) == [False, True, False]

        strategy._model = _BrokenModel()
        entries, exits = strategy.generate_signals(df)
        assert not entries.any()
        assert not exits.any()

    def test_generate_signals_uses_positive_class_probability_for_two_class_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = MLEnsembleStrategy(
            params={"lookback": 5, "entry_threshold": 0.7, "exit_threshold": 0.4}
        )
        df = _make_df(20)
        features = pd.DataFrame({"f1": [1.0, 2.0]}, index=df.index[-2:])
        strategy._model = _FakeClassifier()
        monkeypatch.setattr(strategy, "_extract_features", lambda frame: features)
        monkeypatch.setattr(
            strategy,
            "_apply_meta_labeling",
            lambda frame, proba: pd.Series([True, True], index=proba.index),
        )

        entries, exits = strategy.generate_signals(df)

        assert list(entries.loc[features.index]) == [True, True]
        assert list(exits.loc[features.index]) == [False, False]

    def test_generate_signals_returns_empty_for_lookback_or_feature_gaps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = MLEnsembleStrategy(params={"lookback": 5})
        df = _make_df(3)

        entries, exits = strategy.generate_signals(df)
        assert not entries.any()
        assert not exits.any()

        strategy._model = object()
        monkeypatch.setattr(strategy, "_extract_features", lambda frame: pd.DataFrame())
        entries, exits = strategy.generate_signals(_make_df(10))
        assert not entries.any()
        assert not exits.any()

    def test_train_model_returns_error_on_length_mismatch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = MLEnsembleStrategy()
        monkeypatch.setattr(
            strategy, "_extract_features", lambda df: pd.DataFrame({"x": [1.0, 2.0]})
        )

        result = strategy.train_model(_make_df(5), pd.Series([1, 0, 1]))

        assert result == {"error": "Feature extraction failed or length mismatch"}

    def test_train_model_raises_clear_error_when_sklearn_is_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        strategy = MLEnsembleStrategy()
        original_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.startswith("sklearn"):
                raise ImportError("missing sklearn")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr("builtins.__import__", fake_import)

        with pytest.raises(ImportError, match="scikit-learn required"):
            strategy.train_model(_make_df(5), pd.Series([1, 0, 1, 0, 1]))

    def test_train_model_trains_primary_and_meta_models_and_saves_artifacts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        strategy = MLEnsembleStrategy(params={"model_path": str(tmp_path / "model.joblib")})
        df = _make_df(8)
        features = pd.DataFrame(
            {"f1": [1.0, 2.0, 3.0, 4.0], "f2": [4.0, 5.0, 6.0, 7.0]},
            index=df.index[:4],
        )
        labels = pd.Series([1, 0, 1, 1], index=features.index)
        meta_labels = pd.Series([1, 1, 0, 1], index=features.index)
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

        result = strategy.train_model(df, labels, meta_labels=meta_labels)

        assert result["validation_method"] == "time_series_expanding_oos"
        assert result["cv_accuracy_mean"] == result["oos_accuracy"]
        assert result["cv_accuracy_std"] == 0.0
        assert 0.0 <= result["oos_precision"] <= 1.0
        assert 0.0 <= result["oos_recall"] <= 1.0
        assert 0.0 <= result["oos_brier_score"] <= 1.0
        assert isinstance(result["oos_sharpe"], float)
        assert result["n_features"] == 2
        assert result["n_samples"] == 4
        assert result["n_oos_samples"] > 0
        assert strategy._model is not None
        assert strategy._meta_model is not None
        assert dumps == [
            str(tmp_path / "model.joblib"),
            str(tmp_path / "model_meta.joblib"),
        ]

    def test_train_model_handles_save_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        strategy = MLEnsembleStrategy(params={"model_path": str(tmp_path / "model.joblib")})
        features = pd.DataFrame({"f1": [1.0, 2.0, 3.0, 4.0, 5.0]})
        labels = pd.Series([1, 0, 1, 0, 1])

        monkeypatch.setattr(strategy, "_extract_features", lambda frame: features)

        sklearn = ModuleType("sklearn")
        ensemble = ModuleType("sklearn.ensemble")
        ensemble.GradientBoostingClassifier = _FakeClassifier
        monkeypatch.setitem(sys.modules, "sklearn", sklearn)
        monkeypatch.setitem(sys.modules, "sklearn.ensemble", ensemble)

        joblib = ModuleType("joblib")

        def _raise_dump(model, path):
            raise RuntimeError("disk full")

        joblib.dump = _raise_dump
        monkeypatch.setitem(sys.modules, "joblib", joblib)

        result = strategy.train_model(_make_df(5), labels)

        assert result["n_features"] == 1
        assert result["n_samples"] == 5

    def test_apply_meta_labeling_and_load_model_cover_error_paths(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        strategy = MLEnsembleStrategy(params={"model_path": str(tmp_path / "loaded.joblib")})
        proba = pd.Series([0.2, 0.9], index=[10, 11])

        strategy._meta_model = _BrokenMetaModel()
        approved = strategy._apply_meta_labeling(pd.DataFrame(), proba)
        # ISS-039 fail-closed (odyssey-review RP1): a meta-model that exists but
        # raises on predict must NOT approve-all (that would silently disable the
        # meta-labeling risk filter). Reject-all instead — no entries until the
        # operator resolves the meta-model failure.
        assert not approved.any()

        loaded_paths: list[str] = []
        monkeypatch.setattr(
            Path, "exists", lambda self: self.name in {"loaded.joblib", "loaded_meta.joblib"}
        )

        joblib = ModuleType("joblib")

        def _load(path):
            loaded_paths.append(str(path))
            if str(path).endswith("_meta.joblib"):
                return "meta-model"
            return "primary-model"

        joblib.load = _load
        monkeypatch.setitem(sys.modules, "joblib", joblib)

        strategy._load_model()
        assert strategy._model == "primary-model"
        assert strategy._meta_model == "meta-model"
        assert any(path.endswith("loaded.joblib") for path in loaded_paths)

        joblib.load = lambda path: (_ for _ in ()).throw(RuntimeError("bad model"))
        strategy._load_model()

    def test_apply_meta_labeling_uses_meta_predictions_when_available(self) -> None:
        strategy = MLEnsembleStrategy()
        strategy._meta_model = type(
            "MetaModel",
            (),
            {"predict": staticmethod(lambda features: np.array([1, 0]))},
        )()

        result = strategy._apply_meta_labeling(pd.DataFrame(), pd.Series([0.2, 0.8], index=[1, 2]))

        assert result.tolist() == [True, False]

    def test_bars_to_df_and_required_indicators(self) -> None:
        strategy = MLEnsembleStrategy()
        strategy._bars = [_make_bar(1, 100.0, "BTC/USDT"), _make_bar(2, 101.0, "BTC/USDT")]

        df = strategy._bars_to_df()

        assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "symbol"]
        assert df["symbol"].tolist() == ["BTC/USDT", "BTC/USDT"]
        assert strategy.get_required_indicators() == [{"name": "all_factors", "params": {}}]
