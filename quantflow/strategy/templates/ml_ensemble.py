"""ML ensemble strategy — non-linear factor combination with meta-labeling."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


def _positive_class_probability(model: Any, features: pd.DataFrame) -> np.ndarray:
    probas = np.asarray(model.predict_proba(features), dtype=float)
    if probas.shape[1] == 1:
        return np.ones(len(features), dtype=float) * float(probas[:, 0].mean())

    classes = list(getattr(model, "classes_", []))
    if 1 in classes:
        return probas[:, classes.index(1)]
    return probas[:, -1]


def _time_series_splits(n_samples: int, max_splits: int = 5) -> list[tuple[slice, slice]]:
    if n_samples < 3:
        return []
    n_splits = min(max_splits, max(1, n_samples - 2))
    test_size = max(1, n_samples // (n_splits + 1))
    first_test_start = max(2, n_samples - n_splits * test_size)
    splits = []
    for test_start in range(first_test_start, n_samples, test_size):
        test_end = min(test_start + test_size, n_samples)
        if test_end > test_start:  # pragma: no cover - guard only
            # Unreachable: test_start < n_samples and test_size >= 1 guarantee
            # test_end = min(test_start + test_size, n) > test_start.
            splits.append((slice(0, test_start), slice(test_start, test_end)))
    return splits


def _safe_sharpe(returns: pd.Series) -> float:
    r = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(252))


def _classification_metrics(
    y_true: pd.Series,
    y_pred: pd.Series,
    y_proba: pd.Series,
) -> dict[str, float]:
    true = y_true.astype(int)
    pred = y_pred.astype(int)
    tp = int(((true == 1) & (pred == 1)).sum())
    fp = int(((true == 0) & (pred == 1)).sum())
    fn = int(((true == 1) & (pred == 0)).sum())
    accuracy = float((true == pred).mean()) if len(true) > 0 else 0.0
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    brier = float(np.mean((y_proba.astype(float) - true.astype(float)) ** 2))
    return {
        "accuracy": accuracy,
        "precision": float(precision),
        "recall": float(recall),
        "brier_score": brier,
    }


class MLEnsembleStrategy(StrategyBase):
    """ML ensemble alpha strategy.

    Uses 21 existing factors as features for an sklearn ensemble model.
    Meta-labeling filters: the primary model predicts direction,
    meta-labeling decides whether to act on it.

    Train: run train_model() with labeled data
    Predict: generate_signals() uses the trained model

    Entry: model predict_proba > entry_threshold AND meta_label == 1
    Exit: model predict_proba < exit_threshold OR meta_label == 0
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="ml_ensemble", params=params)
        p = self._params
        self._entry_threshold = p.get("entry_threshold", 0.6)
        self._exit_threshold = p.get("exit_threshold", 0.4)
        self._lookback = p.get("lookback", 252)
        self._retrain_interval = p.get("retrain_interval", 10080)  # bars
        self._model_path = p.get("model_path", "models/ml_ensemble.joblib")

        self._model: Any = None
        self._meta_model: Any = None
        self._feature_cols: list[str] = []
        self._bars: list[Bar] = []
        self._max_bars = self._lookback + 50
        self._bar_count = 0

    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params
        self._load_model()

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar)
        self._bar_count += 1
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]

        if self._model is None or len(self._bars) < self._lookback:
            return

        df = self._bars_to_df()
        if df.empty:
            return

        entries, exits = self.generate_signals(df)
        if entries.empty:
            return

        last_idx = len(entries) - 1
        symbol = bar.symbol

        if entries.iloc[last_idx]:
            ctx.emit_signal(
                symbol, Direction.LONG, strength=0.8, price=bar.close, strategy_id=self.name
            )
        elif exits.iloc[last_idx]:
            ctx.emit_signal(
                symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name
            )

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        if len(df) < self._lookback or self._model is None:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        features = self._extract_features(df)
        if features.empty:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        try:
            probas = self._model.predict_proba(features)
            if probas.shape[1] == 2:
                long_proba = pd.Series(probas[:, 1], index=features.index)
            else:
                long_proba = pd.Series(probas[:, 0], index=features.index)
        except Exception:
            logger.warning("Model prediction failed, returning no signals")
            empty = pd.Series(False, index=df.index)
            return empty, empty

        # Meta-labeling filter
        meta_labels = self._apply_meta_labeling(df, long_proba)

        # Entry: high confidence + meta-label approval
        entries = (long_proba > self._entry_threshold) & meta_labels

        # Exit: low confidence or meta-label rejection
        low_confidence = long_proba < self._exit_threshold
        meta_reject = ~meta_labels
        exits = low_confidence | meta_reject

        return entries.fillna(False), exits.fillna(False)

    def train_model(
        self,
        df: pd.DataFrame,
        labels: pd.Series,
        meta_labels: pd.Series | None = None,
    ) -> dict[str, Any]:
        """Train the ensemble model on labeled data.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV + indicators DataFrame.
        labels : pd.Series
            Binary labels (1=up, 0=down) for supervised learning.
        meta_labels : pd.Series | None
            Meta-labels for trade filtering (1=take, 0=skip).

        Returns
        -------
        dict with training metrics.
        """
        try:
            from sklearn.ensemble import GradientBoostingClassifier
        except ImportError as e:
            raise ImportError("scikit-learn required: pip install scikit-learn") from e

        features = self._extract_features(df)
        if features.empty or len(features) != len(labels):
            return {"error": "Feature extraction failed or length mismatch"}

        # Drop NaN rows
        valid = features.dropna()
        valid_labels = labels.loc[valid.index]
        splits = _time_series_splits(len(valid))
        if not splits:
            return {"error": "Insufficient data for time-series validation"}

        oos_pred = pd.Series(index=valid.index, dtype=int)
        oos_proba = pd.Series(index=valid.index, dtype=float)

        for train_slice, test_slice in splits:
            fold_model = GradientBoostingClassifier(
                n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42
            )
            train_x = valid.iloc[train_slice]
            train_y = valid_labels.iloc[train_slice]
            test_x = valid.iloc[test_slice]
            fold_model.fit(train_x, train_y)
            fold_proba = _positive_class_probability(fold_model, test_x)
            oos_proba.loc[test_x.index] = fold_proba
            oos_pred.loc[test_x.index] = (fold_proba >= 0.5).astype(int)

        evaluated_idx = oos_proba.dropna().index
        if len(evaluated_idx) == 0:
            return {"error": "No out-of-sample predictions produced"}

        y_oos = valid_labels.loc[evaluated_idx].astype(int)
        pred_oos = oos_pred.loc[evaluated_idx].astype(int)
        proba_oos = oos_proba.loc[evaluated_idx].astype(float).clip(0.0, 1.0)

        forward_returns = df["close"].pct_change().shift(-1).reindex(evaluated_idx).fillna(0.0)
        signed_returns = forward_returns.where(pred_oos == 1, -forward_returns)
        oos_sharpe = _safe_sharpe(signed_returns)
        metrics = _classification_metrics(y_oos, pred_oos, proba_oos)

        self._model = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42
        )
        self._model.fit(valid, valid_labels)
        self._feature_cols = list(valid.columns)

        # Train meta-labeling model from primary OOS predictions when available.
        if meta_labels is not None:
            meta_valid = meta_labels.loc[evaluated_idx]
            meta_features = pd.DataFrame(
                {
                    "primary_pred": pred_oos.to_numpy(),
                    "primary_proba": proba_oos.to_numpy(),
                },
                index=evaluated_idx,
            )
            self._meta_model = GradientBoostingClassifier(
                n_estimators=50, max_depth=3, random_state=42
            )
            self._meta_model.fit(meta_features, meta_valid)

        # Save model
        try:
            from joblib import dump

            Path(self._model_path).parent.mkdir(parents=True, exist_ok=True)
            dump(self._model, self._model_path)
            if self._meta_model is not None:
                dump(self._meta_model, self._model_path.replace(".joblib", "_meta.joblib"))
        except Exception as e:
            logger.warning(f"Failed to save model: {e}")

        return {
            "validation_method": "time_series_expanding_oos",
            "cv_accuracy_mean": metrics["accuracy"],
            "cv_accuracy_std": 0.0,
            "oos_accuracy": metrics["accuracy"],
            "oos_precision": metrics["precision"],
            "oos_recall": metrics["recall"],
            "oos_brier_score": metrics["brier_score"],
            "oos_sharpe": oos_sharpe,
            "n_features": len(self._feature_cols),
            "n_samples": len(valid),
            "n_oos_samples": len(evaluated_idx),
        }

    def compute_meta_labels(
        self,
        df: pd.DataFrame,
        entries: pd.Series,
        exits: pd.Series,
        profit_take_pct: float = 0.02,
        stop_loss_pct: float = 0.01,
    ) -> pd.Series:
        """Compute meta-labels from trade outcomes using triple barrier method.

        Returns
        -------
        pd.Series
            Binary meta-labels (1=profitable trade, 0=unprofitable).
        """
        close = df["close"]
        meta = pd.Series(0, index=df.index, dtype=int)

        in_position = False
        entry_price = 0.0

        for i in range(len(close)):
            if entries.iloc[i] and not in_position:
                in_position = True
                entry_price = close.iloc[i]
            elif in_position:
                ret = (close.iloc[i] - entry_price) / entry_price
                if ret >= profit_take_pct or ret <= -stop_loss_pct or exits.iloc[i]:
                    meta.iloc[i] = 1 if ret > 0 else 0
                    in_position = False

        return meta

    def _extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract feature matrix from OHLCV + indicators DataFrame."""
        close = df["close"]
        high = df.get("high", close)
        low = df.get("low", close)
        volume = df.get("volume", pd.Series(1.0, index=df.index))

        features = pd.DataFrame(index=df.index)

        # Momentum features
        for period in [5, 10, 20]:
            features[f"roc_{period}"] = close.pct_change(period)

        # Volatility features
        features["atr_14"] = (high - low).rolling(14).mean()
        for period in [10, 20]:
            features[f"volatility_{period}"] = close.pct_change().rolling(period).std()

        # Volume features
        features["volume_ratio"] = volume / volume.rolling(20).mean().replace(0, 1e-10)

        # Moving average features
        for period in [10, 20, 50]:
            features[f"ma_ratio_{period}"] = close / close.rolling(period).mean()

        # RSI-like feature
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        features["rsi_14"] = 100 - (100 / (1 + gain / loss.replace(0, 1e-10)))

        # MACD-like feature
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        features["macd_hist"] = (ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()

        # BB position
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        features["bb_position"] = (close - bb_mid) / (2 * bb_std.replace(0, 1e-10))

        # Use only available feature columns
        return features.dropna()

    def _apply_meta_labeling(
        self,
        df: pd.DataFrame,
        primary_proba: pd.Series,
    ) -> pd.Series:
        """Apply meta-labeling filter to primary model predictions."""
        if self._meta_model is None:
            # Without meta-model, approve all predictions
            return pd.Series(True, index=primary_proba.index)

        try:
            primary_preds = (primary_proba > 0.5).astype(int)
            meta_features = pd.DataFrame(
                {
                    "primary_pred": primary_preds.values,
                    "primary_proba": primary_proba.values,
                }
            )
            meta_labels = self._meta_model.predict(meta_features)
            return pd.Series(meta_labels.astype(bool), index=primary_proba.index)
        except Exception as e:
            # ISS-039 fail-closed (odyssey-review RP1): a meta-model that EXISTS
            # but raises on predict is a configured risk filter that just failed.
            # Returning True (approve-all) here would silently disable meta-
            # labeling — every primary signal would pass unfiltered. Reject-all
            # (False) instead: no entries until the operator sees zero trades and
            # investigates. This is distinct from the `_meta_model is None` branch
            # above, where no filter was configured and approve-all is by design.
            logger.error(
                "Meta-model predict failed — fail-closed reject-all (no entries "
                "will be generated until resolved): %s",
                e,
            )
            return pd.Series(False, index=primary_proba.index)

    def _load_model(self) -> None:
        """Load pre-trained model from disk."""
        try:
            from joblib import load

            path = Path(self._model_path)
            if path.exists():
                self._model = load(path)
                meta_path = str(path).replace(".joblib", "_meta.joblib")
                if Path(meta_path).exists():
                    self._meta_model = load(meta_path)
                logger.info(f"Loaded ML model from {path}")
        except Exception as e:
            logger.warning(f"Failed to load model: {e}")

    def _bars_to_df(self) -> pd.DataFrame:
        if not self._bars:
            return pd.DataFrame()
        data = {
            "timestamp": [b.timestamp for b in self._bars],
            "open": [b.open for b in self._bars],
            "high": [b.high for b in self._bars],
            "low": [b.low for b in self._bars],
            "close": [b.close for b in self._bars],
            "volume": [b.volume for b in self._bars],
        }
        df = pd.DataFrame(data)
        df["symbol"] = self._bars[0].symbol
        return df

    def get_required_indicators(self) -> list[dict[str, Any]]:
        return [
            {"name": "all_factors", "params": {}},
        ]
