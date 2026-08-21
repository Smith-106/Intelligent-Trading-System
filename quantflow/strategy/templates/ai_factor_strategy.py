"""AI factor strategy — registry-driven model probability blended with momentum.

s4 (T-s4-03): consumes models registered in the s3 :class:`ModelRegistry`
(status paper/live). The model's predicted P(up) is used as a factor that
filters/amplifies a base momentum signal:

- Base signal: fast/slow SMA crossover (long if fast > slow, short if fast < slow).
- AI factor: model P(up) >= ai_entry_threshold boosts the base entry;
  P(up) <= 1 - ai_entry_threshold blocks it (direction filter).
- Fail-open at the signal layer: when the registry has no usable model or
  prediction fails, the strategy degrades to the plain momentum signal
  (base-only). Registry *access* itself is fail-closed (unreadable registry
  dir → treated as no model, not an exception).

Contrast with ``ml_ensemble``: that template self-trains its models inside the
strategy; this one consumes externally validated, registry-gated models — the
s3 → s4 handoff.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from quantflow.common.models import Bar, Direction
from quantflow.strategy.base import StrategyBase, StrategyContext

logger = logging.getLogger(__name__)

STATUS_LIVE = "live"
STATUS_PAPER = "paper"
_USABLE_STATUSES = (STATUS_LIVE, STATUS_PAPER)


class AIFactorStrategy(StrategyBase):
    """Registry-driven AI factor strategy.

    Entry long: fast MA > slow MA AND model P(up) >= ai_entry_threshold.
    Entry short: fast MA < slow MA AND model P(up) <= 1 - ai_entry_threshold.
    Exit: MA crossover reverts (or model confidence flips to the opposite side).
    Degradation: no usable model → pure momentum (base signal only).
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(name="ai_factor", params=params)
        p = self._params
        self._fast_period = p.get("fast_ma_period", 10)
        self._slow_period = p.get("slow_ma_period", 30)
        self._ai_entry_threshold = p.get("ai_entry_threshold", 0.55)
        self._ai_exit_threshold = p.get("ai_exit_threshold", 0.45)
        self._registry_dir = p.get("registry_dir", "./data/models")
        self._model_id: str | None = p.get("model_id", None)
        self._min_history = self._slow_period + 5

        self._bars: list[Bar] = []
        self._max_bars = self._slow_period * 3
        self._model: Any = None
        self._model_loaded = False
        self._model_error: str | None = None

    # ------------------------------------------------------------------
    # Model loading (lazy — registry consumed only when first needed)
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """Load the registry-gated model (paper/live) for prediction.

        Fail-closed registry access: any error (missing dir, corrupt JSON,
        unknown id) is logged and treated as "no model" → base-signal
        degradation, never a raised exception at signal time.
        """
        if self._model_loaded:
            return
        self._model_loaded = True
        try:
            from quantflow.strategy.model_registry import ModelRegistry

            registry = ModelRegistry(self._registry_dir)
            candidate = self._model_id
            if candidate is None:
                entries = [e for e in registry.list_models() if e.get("status") in _USABLE_STATUSES]
                if not entries:
                    logger.warning(
                        "ai_factor: no paper/live models in registry %s", self._registry_dir
                    )
                    return
                # Prefer live models; newest first.
                entries.sort(key=lambda e: str(e.get("registered_at", "")), reverse=True)
                candidate = str(entries[0]["model_id"])
            entry = registry.get(candidate)
            if entry is None or entry.get("status") not in _USABLE_STATUSES:
                logger.warning(
                    "ai_factor: model %s not usable (status=%s)",
                    candidate,
                    entry and entry.get("status"),
                )
                return
            model_cls = entry.get("model_cls", "")
            self._model = _instantiate_model(model_cls)
            if self._model is None:
                logger.warning("ai_factor: unknown model_cls %r", model_cls)
                return
            self._model_id = candidate
            logger.info("ai_factor: loaded model %s (%s)", candidate, model_cls)
        except Exception as exc:  # pragma: no cover - defensive
            self._model_error = str(exc)
            logger.warning("ai_factor: registry load failed, degrading to momentum: %s", exc)

    # ------------------------------------------------------------------
    # StrategyBase interface
    # ------------------------------------------------------------------
    def on_init(self, ctx: StrategyContext) -> None:
        ctx.params = self._params
        self._load_model()

    def on_bar(self, ctx: StrategyContext, bar: Bar) -> None:
        self._bars.append(bar)
        if len(self._bars) > self._max_bars:
            self._bars = self._bars[-self._max_bars :]
        if len(self._bars) < self._min_history:
            return
        self._load_model()
        df = _bars_to_df(self._bars)
        entries, exits = self.generate_signals(df)
        if entries.empty:
            return
        last_idx = len(entries) - 1
        if entries.iloc[last_idx]:
            ctx.emit_signal(
                bar.symbol, Direction.LONG, strength=0.8, price=bar.close, strategy_id=self.name
            )
        elif exits.iloc[last_idx]:
            ctx.emit_signal(
                bar.symbol, Direction.FLAT, strength=0.5, price=bar.close, strategy_id=self.name
            )

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Vectorized signal generation.

        Returns (entries, exits) boolean Series. Without a usable model this
        is pure fast/slow momentum; with a model, the AI factor gates entries.
        """
        if len(df) < self._min_history:
            empty = pd.Series(False, index=df.index)
            return empty, empty

        close = df["close"]
        fast_ma = close.rolling(self._fast_period).mean()
        slow_ma = close.rolling(self._slow_period).mean()
        base_long = fast_ma > slow_ma
        base_short = fast_ma < slow_ma

        if self._model is None:
            entries = base_long
            exits = base_short
        else:
            try:
                proba = self._predict_up(df)
                # AI gate: only act when the model agrees with the momentum side.
                entries = base_long & (proba >= self._ai_entry_threshold)
                exits = base_short | ((~base_long) & (proba <= self._ai_exit_threshold))
            except Exception:
                logger.warning("ai_factor: prediction failed, degrading to momentum")
                entries = base_long
                exits = base_short

        # Shift: a signal is actionable on the bar AFTER the condition flips.
        entries = entries & ~entries.shift(1, fill_value=False)
        exits = exits & ~exits.shift(1, fill_value=False)
        return entries, exits

    # ------------------------------------------------------------------
    # Prediction helpers
    # ------------------------------------------------------------------
    def _predict_up(self, df: pd.DataFrame) -> pd.Series:
        """Predict P(up) from the trained model on the feature matrix."""
        features = self._feature_matrix(df)
        if features.empty:
            return pd.Series(0.5, index=df.index)
        probas = self._model.predict_proba(features)
        if probas.shape[1] >= 2:
            return pd.Series(probas[:, 1], index=df.index)
        return pd.Series(probas[:, 0], index=df.index)

    def _feature_matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        """Feature matrix aligned to df index (returns/vol/momentum)."""
        close = df["close"]
        ret_1 = close.pct_change()
        ret_5 = close.pct_change(5)
        vol_20 = close.pct_change().rolling(20).std()
        mom_10 = close / close.shift(10) - 1.0
        return pd.concat([ret_1, ret_5, vol_20, mom_10], axis=1).fillna(0.0)


def _instantiate_model(model_cls: str) -> Any:
    """Instantiate a registry model class by name (allowlisted classifiers).

    Only a fixed allowlist is supported; unknown classes return None so the
    strategy degrades to the momentum baseline (never raises at signal time).
    """
    if model_cls == "RandomForestClassifier":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier()
    if model_cls == "LogisticRegression":
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression()
    if model_cls == "GradientBoostingClassifier":
        from sklearn.ensemble import GradientBoostingClassifier

        return GradientBoostingClassifier()
    logger.warning("ai_factor: model_cls %r not in allowlist", model_cls)
    return None


def _bars_to_df(bars: list[Bar]) -> pd.DataFrame:
    """Convert Bar objects to an OHLCV DataFrame (event-driven path)."""
    return pd.DataFrame(
        {
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        }
    )
