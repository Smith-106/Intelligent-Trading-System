"""Divergence detector for Elliott Wave analysis.

Detects three types of divergence at wave endpoints:
- Price-MACD divergence (W5 exhaustion, B-wave weakness)
- Price-Volume divergence (W5 exhaustion, W3 confirmation)
- Price-RSI divergence

Interface uses WaveCount (C-003) to enforce wave-degree comparison,
preventing adjacent-pivot false signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from quantflow.indicators.base import FactorBase
from quantflow.indicators.wave_models import WaveCount, WavePattern, WaveSegment


@dataclass
class Divergence:
    """A single detected divergence signal."""

    divergence_type: str  # "macd_bearish", "macd_bullish", "volume_bearish", "volume_bullish", "rsi_bearish", "rsi_bullish"
    wave_ref: int  # which wave the divergence relates to (e.g. 5 for W5 top)
    strength: float  # 0.0-1.0, how significant the divergence is
    price_at_div: float
    indicator_at_div: float


@dataclass
class DivergenceResult:
    """Complete divergence detection result."""

    divergences: list[Divergence] = field(default_factory=list)
    bearish: bool = False  # any bearish divergence detected
    bullish: bool = False  # any bullish divergence detected


class DivergenceDetector(FactorBase):
    """Wave-degree divergence detector.

    Per C-003, the interface uses WaveCount to enforce wave-degree
    comparison. This prevents comparing arbitrary adjacent pivots
    and ensures divergence is evaluated at the wave level (W5 vs W3).
    """

    name = "divergence"

    def compute(self, df: pd.DataFrame, **params: Any) -> pd.Series:
        """Compute divergence and return a composite signal Series."""
        wave_count = params.get("wave_count")
        if wave_count is None:
            return pd.Series(0, index=df.index, dtype=int)

        result = self.detect(wave_count, df)
        signal = pd.Series(0, index=df.index, dtype=int)
        if result.bearish:
            signal.iloc[-1] = -1
        elif result.bullish:
            signal.iloc[-1] = 1
        return signal

    def detect(
        self,
        wave_count: WaveCount,
        df: pd.DataFrame,
    ) -> DivergenceResult:
        """Detect divergence from WaveCount and OHLCV data.

        Args:
            wave_count: Current wave count from WaveIdentifier.
            df: OHLCV DataFrame with computed indicators (MACD, RSI, volume).

        Returns:
            DivergenceResult with detected divergences.
        """
        if wave_count.pattern != WavePattern.IMPULSE:
            return DivergenceResult()

        waves = wave_count.waves
        divergences: list[Divergence] = []
        bearish = False
        bullish = False

        # MACD divergence: W5 vs W3 comparison (SME-05)
        if all(k in waves for k in [3, 5]) and "macd_histogram" in df.columns:
            macd_div = self._check_macd_divergence(waves, df)
            if macd_div:
                divergences.append(macd_div)
                if macd_div.divergence_type.startswith("macd_bearish"):
                    bearish = True
                elif macd_div.divergence_type.startswith("macd_bullish"):
                    bullish = True

        # Volume divergence: W5 vs W3
        if all(k in waves for k in [3, 5]) and "volume" in df.columns:
            vol_div = self._check_volume_divergence(waves, df)
            if vol_div:
                divergences.append(vol_div)
                if vol_div.divergence_type.startswith("volume_bearish"):
                    bearish = True

        # RSI divergence: W2/W4 bottom vs W1/W3
        if all(k in waves for k in [2]) and "rsi_14" in df.columns:
            rsi_div = self._check_rsi_divergence(waves, df)
            if rsi_div:
                divergences.append(rsi_div)
                if rsi_div.divergence_type.startswith("rsi_bullish"):
                    bullish = True

        return DivergenceResult(
            divergences=divergences,
            bearish=bearish,
            bullish=bullish,
        )

    def _check_macd_divergence(
        self,
        waves: dict[int, WaveSegment],
        df: pd.DataFrame,
    ) -> Divergence | None:
        """Check MACD histogram divergence between W5 and W3 peaks."""
        w3 = waves[3]
        w5 = waves.get(5)
        if w5 is None:
            return None

        macd = df["macd_histogram"]
        is_bullish = w3.end.price > w3.start.price

        w3_idx = w3.end.index
        w5_idx = w5.end.index

        if w3_idx >= len(macd) or w5_idx >= len(macd):
            return None

        w3_macd = float(macd.iloc[w3_idx])
        w5_macd = float(macd.iloc[w5_idx])

        if is_bullish:
            # Bearish divergence: W5 price higher but MACD lower
            if w5.end.price > w3.end.price and w5_macd < w3_macd:
                strength = min(1.0, abs(w3_macd - w5_macd) / max(abs(w3_macd), 0.001))
                return Divergence(
                    divergence_type="macd_bearish",
                    wave_ref=5,
                    strength=strength,
                    price_at_div=w5.end.price,
                    indicator_at_div=w5_macd,
                )
        else:
            # Bullish divergence: W5 price lower but MACD higher (less negative)
            if w5.end.price < w3.end.price and w5_macd > w3_macd:
                strength = min(1.0, abs(w5_macd - w3_macd) / max(abs(w3_macd), 0.001))
                return Divergence(
                    divergence_type="macd_bullish",
                    wave_ref=5,
                    strength=strength,
                    price_at_div=w5.end.price,
                    indicator_at_div=w5_macd,
                )

        return None

    def _check_volume_divergence(
        self,
        waves: dict[int, WaveSegment],
        df: pd.DataFrame,
    ) -> Divergence | None:
        """Check volume divergence at W5 vs W3."""
        w3 = waves[3]
        w5 = waves.get(5)
        if w5 is None:
            return None

        volume = df["volume"]
        is_bullish = w3.end.price > w3.start.price

        # Compare volume at W3 and W5 peak bars
        w3_idx = w3.end.index
        w5_idx = w5.end.index

        if w3_idx >= len(volume) or w5_idx >= len(volume):
            return None

        w3_vol = float(volume.iloc[w3_idx])
        w5_vol = float(volume.iloc[w5_idx])

        if is_bullish:
            # W5 exhaustion: price rises but volume shrinks
            if w5.end.price > w3.end.price and w5_vol < w3_vol * 0.7:
                strength = min(1.0, (w3_vol - w5_vol) / max(w3_vol, 0.001))
                return Divergence(
                    divergence_type="volume_bearish",
                    wave_ref=5,
                    strength=strength,
                    price_at_div=w5.end.price,
                    indicator_at_div=w5_vol,
                )
        else:
            if w5.end.price < w3.end.price and w5_vol < w3_vol * 0.7:
                strength = min(1.0, (w3_vol - w5_vol) / max(w3_vol, 0.001))
                return Divergence(
                    divergence_type="volume_bullish",
                    wave_ref=5,
                    strength=strength,
                    price_at_div=w5.end.price,
                    indicator_at_div=w5_vol,
                )

        return None

    def _check_rsi_divergence(
        self,
        waves: dict[int, WaveSegment],
        df: pd.DataFrame,
    ) -> Divergence | None:
        """Check RSI divergence at W2 bottom (bullish).

        W19a: compare W2 end against the **W1 extreme (W1 end peak)**, not W1
        origin. Iron-law-valid W2 rarely undercuts W1 start, so the old
        ``w2.end < w1.start * 0.95`` gate almost never fired. Bullish signal:
        deep retracement of W1 amplitude with RSI holding up vs RSI at W1 peak.
        """
        w2 = waves.get(2)
        w1 = waves.get(1)
        if w2 is None or w1 is None:
            return None

        rsi = df["rsi_14"]
        w1_idx = w1.end.index
        w2_idx = w2.end.index

        if w1_idx >= len(rsi) or w2_idx >= len(rsi):
            return None

        is_bullish = w1.end.price > w1.start.price

        if is_bullish:
            w1_amp = abs(w1.end.price - w1.start.price)
            if w1_amp <= 0:
                return None
            # Retracement measured from W1 peak (end), not origin (start).
            retracement = abs(w1.end.price - w2.end.price) / w1_amp
            w1_rsi = float(rsi.iloc[w1_idx])
            w2_rsi = float(rsi.iloc[w2_idx])
            # Deep pullback (≥50% of W1) with RSI not collapsing vs W1-peak RSI.
            if retracement >= 0.5 and w2_rsi > w1_rsi and w2_rsi > 30:
                strength = min(1.0, abs(w2_rsi - w1_rsi) / max(abs(w1_rsi), 0.001))
                return Divergence(
                    divergence_type="rsi_bullish",
                    wave_ref=2,
                    strength=strength,
                    price_at_div=w2.end.price,
                    indicator_at_div=w2_rsi,
                )

        return None
