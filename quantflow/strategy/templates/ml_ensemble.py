"""ML ensemble strategy — non-linear factor combination with meta-labeling."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)


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
            from sklearn.model_selection import cross_val_score
        except ImportError as e:
            raise ImportError("scikit-learn required: pip install scikit-learn") from e

        features = self._extract_features(df)
        if features.empty or len(features) != len(labels):
            return {"error": "Feature extraction failed or length mismatch"}

        # Drop NaN rows
        valid = features.dropna()
        valid_labels = labels.loc[valid.index]

        self._model = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42
        )
        self._model.fit(valid, valid_labels)
        self._feature_cols = list(valid.columns)

        cv_scores = cross_val_score(self._model, valid, valid_labels, cv=5, scoring="accuracy")

        # Train meta-labeling model if meta_labels provided
        if meta_labels is not None:
            meta_valid = meta_labels.loc[valid.index]
            primary_preds = self._model.predict(valid)
            meta_features = pd.DataFrame(
                {
                    "primary_pred": primary_preds,
                    "primary_proba": self._model.predict_proba(valid)[:, 1]
                    if self._model.n_classes_ == 2
                    else self._model.predict_proba(valid)[:, 0],
                }
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
            "cv_accuracy_mean": float(cv_scores.mean()),
            "cv_accuracy_std": float(cv_scores.std()),
            "n_features": len(self._feature_cols),
            "n_samples": len(valid),
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
        except Exception:
            return pd.Series(True, index=primary_proba.index)

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
