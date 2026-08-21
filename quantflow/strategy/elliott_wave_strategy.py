"""Liu Yudong Elliott Wave trading strategy.

Implements StrategyBase with five wave-segment trading rules:
1. W2-end entry (best positioning point)
2. W3 trend-following entry (strongest momentum)
3. W4-end entry (catching W5)
4. W5-top exit/short
5. B-wave-end exit/short

All rule parameters are exposed and configurable (S-003).
Uses incremental signal generation to prevent look-ahead bias (CORR-019).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from quantflow.indicators.critical_level import CriticalLevelDetector
from quantflow.indicators.divergence import DivergenceDetector, DivergenceResult
from quantflow.indicators.fibonacci import FibonacciCalculator, FibonacciLevels
from quantflow.indicators.wave_channel import ChannelResult, WaveChannel
from quantflow.indicators.wave_identifier import WaveIdentifier
from quantflow.indicators.wave_models import AnalysisMode, WavePattern, WaveSegment
from quantflow.indicators.zigzag import PivotSequence, ZigZagIndicator
from quantflow.signal.wave_signal_generator import (
    InvalidationSeverity,
    WaveInvalidationChecker,
    WaveSignalGenerator,
)
from quantflow.strategy.base import StrategyBase


@dataclass
class WaveContext:
    """Wave context attached to every signal for downstream consumption."""

    current_wave: int
    wave_pattern: WavePattern
    confidence: float
    trigger_rule: str
    critical_levels: dict[str, float] | None = None
    fibonacci_targets: dict[float, float] | None = None


class LiuYudongWaveStrategy(StrategyBase):
    """Liu Yudong style Elliott Wave strategy.

    Renamed from ElliottWaveStrategy to avoid conflict with the
    template version at quantflow/strategy/templates/elliott_wave.py
    (CORR-003). Inherits StrategyBase per project architecture (CORR-015).

    Uses incremental signal generation: on each bar, only data up to
    the current bar is used for ZigZag and wave identification,
    preventing look-ahead bias in backtesting (CORR-019).
    """

    name = "liu_yudong_wave"

    def __init__(self, params: dict[str, Any] | None = None):
        super().__init__(name=self.name, params=params or {})
        config = params or {}
        self.wave_identifier = WaveIdentifier()
        self.fibonacci_calc = FibonacciCalculator()
        self.critical_level_det = CriticalLevelDetector()
        self.wave_channel = WaveChannel()
        self.divergence_det = DivergenceDetector()
        self.zigzag = ZigZagIndicator()
        # W19a: wire signal enrich + invalidation (previously unit-tested only)
        self.wave_signal_gen = WaveSignalGenerator()
        self.invalidation_checker = WaveInvalidationChecker(
            max_consecutive_stops=int(config.get("max_consecutive_stops", 3))
        )
        self._last_invalidation_events: list[Any] = []

        # Configurable parameters (S-003)
        self.zigzag_thresholds = config.get("zigzag_thresholds", [0.03, 0.05, 0.08, 0.12, 0.15])
        self.min_overlap_ratio = config.get("min_overlap_ratio", 0.8)
        self.analysis_mode = AnalysisMode(config.get("analysis_mode", "progressive"))

        # W2-end entry params
        self.w2_retracement_min = config.get("w2_retracement_min", 0.5)
        self.w2_retracement_max = config.get("w2_retracement_max", 0.618)

        # W3 trend-following params
        self.w3_volume_surge = config.get("w3_volume_surge", 1.5)

        # W4-end entry params
        self.w4_retracement_min = config.get("w4_retracement_min", 0.382)
        self.w4_retracement_max = config.get("w4_retracement_max", 0.5)

        # W5 exit params
        self.w5_divergence_threshold = config.get("w5_divergence_threshold", 0.3)

        # B-wave exit params
        self.b_retracement_ratios = config.get("b_retracement_ratios", [0.382, 0.5, 0.618])

        # Incremental mode: window size for look-ahead-free computation
        self.incremental_window = config.get("incremental_window", 200)

        # W18a: pivot fidelity / anti-repaint / consensus visibility
        # require_confirmed_pivots=True (default): drop trailing in-progress pivot
        # so PROGRESSIVE labels do not trade on a flip-able extreme.
        self.require_confirmed_pivots = bool(config.get("require_confirmed_pivots", True))
        # allow_degraded_consensus=False (default): skip windows where ZigZag
        # fell back to single-threshold (degraded=True) — fail-closed.
        self.allow_degraded_consensus = bool(config.get("allow_degraded_consensus", False))
        # W19a: when True (default), hard invalidation on the window exit bar marks exit
        self.use_invalidation_exits = bool(config.get("use_invalidation_exits", True))

    def on_init(self, ctx: Any) -> None:
        """Initialize strategy with context."""
        pass

    def on_bar(self, ctx: Any, bar: Any) -> None:
        """Process a new bar: accumulate window, re-run signals, emit on last bar.

        W19a: bridges the previous no-op ``on_bar`` so paper/live event paths
        can produce entries/exits. Uses the same causal ``generate_signals``
        path (CORR-019) on the accumulated frame.
        """
        if not hasattr(self, "_bar_rows"):
            self._bar_rows: list[dict[str, Any]] = []
        row = {
            "open": float(getattr(bar, "open", 0.0)),
            "high": float(getattr(bar, "high", 0.0)),
            "low": float(getattr(bar, "low", 0.0)),
            "close": float(getattr(bar, "close", 0.0)),
            "volume": float(getattr(bar, "volume", 0.0)),
            "timestamp": int(getattr(bar, "timestamp", 0) or 0),
        }
        self._bar_rows.append(row)
        # Cap memory: keep last incremental_window * 2 bars
        max_rows = max(self.incremental_window * 2, 100)
        if len(self._bar_rows) > max_rows:
            self._bar_rows = self._bar_rows[-max_rows:]

        if len(self._bar_rows) < 20:
            return

        df = pd.DataFrame(self._bar_rows)
        entries, exits = self.generate_signals(df)
        last_i = len(df) - 1
        if bool(entries.iloc[last_i]) or bool(exits.iloc[last_i]):
            # Prefer emit_signal when StrategyBase provides it; else no-op.
            emit = getattr(self, "emit_signal", None)
            if callable(emit):
                from quantflow.common.models import Direction, Signal

                if bool(exits.iloc[last_i]):
                    emit(
                        Signal(
                            symbol=str(getattr(bar, "symbol", "")),
                            direction=Direction.FLAT,
                            price=float(row["close"]),
                            strategy_id=self.name,
                            timestamp=int(row["timestamp"]),
                        )
                    )
                elif bool(
                    entries.iloc[last_i]
                ):  # pragma: no branch — L146 guarantees entries when exits is False
                    emit(
                        Signal(
                            symbol=str(getattr(bar, "symbol", "")),
                            direction=Direction.LONG,
                            price=float(row["close"]),
                            strategy_id=self.name,
                            timestamp=int(row["timestamp"]),
                        )
                    )

    def generate_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Generate entry and exit signals from OHLCV data.

        Uses incremental computation to prevent look-ahead bias (CORR-019):
        for each bar i, only data from bar 0 to bar i is used for
        ZigZag detection and wave identification.

        Args:
            df: DataFrame with columns [open, high, low, close, volume].

        Returns:
            Tuple of (entries, exits) boolean Series.
        """
        entries = pd.Series(False, index=df.index, dtype=bool)
        exits = pd.Series(False, index=df.index, dtype=bool)

        n = len(df)
        if n < 20:
            return entries, exits

        # Incremental signal generation (CORR-019 fix)
        # Process in windows to avoid look-ahead bias
        step = max(self.incremental_window // 4, 50)

        for end_idx in range(20, n, step):
            # Use only data up to current position — no future leakage
            window_df = df.iloc[:end_idx].copy()

            # W18a: use compute_pivot_sequence for real high/low pivot prices
            # (marker Series + close substitution dropped as the primary path).
            pivots = self._detect_pivots(window_df)
            if pivots is None:
                continue

            # Identify wave pattern on windowed data
            wave_count = self.wave_identifier.identify(pivots, mode=self.analysis_mode)

            if wave_count.pattern == WavePattern.UNKNOWN:
                continue

            # Compute supporting indicators
            fib_levels = self.fibonacci_calc.calculate(wave_count)
            critical_levels = self.critical_level_det.detect(wave_count)
            channel = self.wave_channel.calculate(window_df, wave_count)

            # Add MACD/RSI if available for divergence check
            if "macd_histogram" not in window_df.columns:
                window_df["macd_histogram"] = self._compute_macd_histogram(window_df["close"])
            if "rsi_14" not in window_df.columns:
                window_df["rsi_14"] = self._compute_rsi(window_df["close"])

            divergence = self.divergence_det.detect(wave_count, window_df)

            # Apply trading rules — only mark signals in the NEW portion of data
            # to avoid overwriting previously confirmed signals
            waves = wave_count.waves
            is_bullish = (
                wave_count.pattern == WavePattern.IMPULSE
                and 1 in waves
                and waves[1].end.price > waves[1].start.price
            )

            new_start = max(0, end_idx - step)

            # Rule 1: W2-end entry
            if self._check_w2_entry(window_df, waves, is_bullish):
                if 2 in waves:
                    idx = waves[2].end.index
                    if new_start <= idx < end_idx and idx < n:
                        entries.iat[idx] = True

            # Rule 2: W3 trend-following entry
            if self._check_w3_entry(window_df, waves, is_bullish):
                if 1 in waves:
                    idx = waves[1].end.index
                    if new_start <= idx < end_idx and idx < n:
                        entries.iat[idx] = True

            # Rule 3: W4-end entry
            if self._check_w4_entry(window_df, waves, is_bullish):
                if 4 in waves:
                    idx = waves[4].end.index
                    if new_start <= idx < end_idx and idx < n:
                        entries.iat[idx] = True

            # Rule 4: W5-top exit
            if self._check_w5_exit(window_df, waves, is_bullish, divergence, channel, fib_levels):
                if 5 in waves:
                    idx = waves[5].end.index
                    if new_start <= idx < end_idx and idx < n:
                        exits.iat[idx] = True

            # Rule 5: B-wave exit
            if wave_count.pattern == WavePattern.CORRECTIVE:
                if self._check_b_wave_exit(window_df, waves):
                    if -2 in waves:
                        idx = waves[-2].end.index
                        if new_start <= idx < end_idx and idx < n:
                            exits.iat[idx] = True

            # W19a: WaveInvalidationChecker — hard breach → exit on last bar of window
            levels_list = getattr(critical_levels, "levels", None)
            if (
                self.use_invalidation_exits
                and critical_levels is not None
                and isinstance(levels_list, list)
            ):
                last_close = float(window_df["close"].iloc[-1])
                events = self.invalidation_checker.check(wave_count, critical_levels, last_close)
                self._last_invalidation_events = events
                hard = [e for e in events if e.severity == InvalidationSeverity.HARD]
                if hard:
                    idx = end_idx - 1
                    if (
                        new_start <= idx < end_idx and idx < n
                    ):  # pragma: no branch — idx=end_idx-1 and step>=50 guarantee bounds
                        exits.iat[idx] = True

        return entries, exits

    def _detect_pivots(self, df: pd.DataFrame) -> PivotSequence | None:
        """Run consensus ZigZag with real high/low prices (W18a).

        Returns None when the window should be skipped (degraded consensus and
        allow_degraded_consensus is False).
        """
        high = df["high"] if "high" in df.columns else df["close"]
        low = df["low"] if "low" in df.columns else df["close"]
        if "timestamp" in df.columns:
            timestamps = df["timestamp"]
        else:
            timestamps = pd.Series(range(len(df)), index=df.index, dtype=int)

        seq = self.zigzag.compute_pivot_sequence(
            high,
            low,
            timestamps,
            thresholds=self.zigzag_thresholds,
            min_overlap_ratio=self.min_overlap_ratio,
        )
        if seq.degraded and not self.allow_degraded_consensus:
            return None
        if self.require_confirmed_pivots:
            return seq.with_confirmed_only()
        return seq

    def _extract_pivots(self, pivot_series: pd.Series, df: pd.DataFrame) -> PivotSequence:
        """Convert pivot marker Series back to PivotSequence (legacy helper).

        W18a: prefer high for HIGH pivots and low for LOW pivots when columns
        exist; close is only a last-resort fallback.
        """
        from quantflow.indicators.zigzag import PivotDirection, PivotPoint, PivotSequence

        high = df["high"] if "high" in df.columns else df["close"]
        low = df["low"] if "low" in df.columns else df["close"]

        pivots_list: list[PivotPoint] = []
        for idx_pos in range(len(pivot_series)):
            val = int(pivot_series.iloc[idx_pos])
            if val != 0:
                price = float(high.iloc[idx_pos]) if val == 1 else float(low.iloc[idx_pos])
                pivots_list.append(
                    PivotPoint(
                        index=idx_pos,
                        price=price,
                        direction=PivotDirection.HIGH if val == 1 else PivotDirection.LOW,
                        confidence=1.0,
                    )
                )

        return PivotSequence(
            pivots=pivots_list,
            overlap_ratio=1.0,
            thresholds_used=self.zigzag_thresholds,
            degraded=False,
            consensus_n=0,
        )

    def _check_w2_entry(
        self,
        df: pd.DataFrame,
        waves: dict[int, WaveSegment],
        is_bullish: bool,
    ) -> bool:
        """Rule 1: W2-end entry — best positioning point."""
        if 1 not in waves or 2 not in waves:
            return False
        w1 = waves[1]
        w2 = waves[2]
        if w1.amplitude() <= 0:
            return False
        retracement = w2.amplitude() / w1.amplitude()
        if not (self.w2_retracement_min <= retracement <= self.w2_retracement_max):
            return False
        if "volume" in df.columns and w2.end.index < len(df):
            w1_avg_vol = df["volume"].iloc[max(0, w1.start.index) : w1.end.index + 1].mean()
            w2_avg_vol = df["volume"].iloc[max(0, w2.start.index) : w2.end.index + 1].mean()
            if pd.notna(w1_avg_vol) and pd.notna(w2_avg_vol) and w1_avg_vol > 0:
                if w2_avg_vol > w1_avg_vol * 0.8:
                    return False
        return True

    def _check_w3_entry(
        self,
        df: pd.DataFrame,
        waves: dict[int, WaveSegment],
        is_bullish: bool,
    ) -> bool:
        """Rule 2: W3 trend-following entry — strongest momentum."""
        if 1 not in waves or 3 not in waves:
            return False
        w1 = waves[1]
        w3 = waves[3]
        if w3.amplitude() < w1.amplitude():
            return False
        if "volume" in df.columns and w3.end.index < len(df):
            avg_vol = df["volume"].iloc[max(0, w3.start.index) : w3.end.index + 1].mean()
            if w3.start.index >= 20:
                baseline_vol = df["volume"].rolling(20).mean().iloc[w3.start.index]
                if pd.notna(baseline_vol) and baseline_vol > 0:
                    if avg_vol < baseline_vol * self.w3_volume_surge:
                        return False
        return True

    def _check_w4_entry(
        self,
        df: pd.DataFrame,
        waves: dict[int, WaveSegment],
        is_bullish: bool,
    ) -> bool:
        """Rule 3: W4-end entry — catching W5."""
        if 3 not in waves or 4 not in waves:
            return False
        w3 = waves[3]
        w4 = waves[4]
        if w3.amplitude() <= 0:
            return False
        retracement = w4.amplitude() / w3.amplitude()
        if not (self.w4_retracement_min <= retracement <= self.w4_retracement_max):
            return False
        if "volume" in df.columns and w4.end.index < len(df):
            w3_avg_vol = df["volume"].iloc[max(0, w3.start.index) : w3.end.index + 1].mean()
            w4_avg_vol = df["volume"].iloc[max(0, w4.start.index) : w4.end.index + 1].mean()
            if pd.notna(w3_avg_vol) and pd.notna(w4_avg_vol) and w3_avg_vol > 0:
                if w4_avg_vol > w3_avg_vol * 0.8:
                    return False
        return True

    def _check_w5_exit(
        self,
        df: pd.DataFrame,
        waves: dict[int, WaveSegment],
        is_bullish: bool,
        divergence: DivergenceResult | None = None,
        channel: ChannelResult | None = None,
        fib_levels: FibonacciLevels | None = None,
    ) -> bool:
        """Rule 4: W5-top exit/short."""
        if 5 not in waves:
            return False
        signals = 0
        if divergence and divergence.bearish:
            for d in divergence.divergences:
                if d.wave_ref == 5 and d.strength >= self.w5_divergence_threshold:
                    signals += 1
                    break
        if "volume" in df.columns and 3 in waves:
            w3 = waves[3]
            w5 = waves[5]
            if w5.end.index < len(df) and w3.end.index < len(df):
                w3_vol = df["volume"].iloc[w3.end.index]
                w5_vol = df["volume"].iloc[w5.end.index]
                if pd.notna(w3_vol) and pd.notna(w5_vol) and w3_vol > 0:
                    if w5_vol < w3_vol * 0.7:
                        signals += 1
        if channel and channel.w5_target is not None:
            w5 = waves[5]
            if (is_bullish and w5.end.price >= channel.w5_target * 0.98) or (
                not is_bullish and w5.end.price <= channel.w5_target * 1.02
            ):
                signals += 1
        if fib_levels and 5 in waves:
            w5 = waves[5]
            ext_1618 = fib_levels.extension.get(1.618)
            if ext_1618 is not None:
                if (is_bullish and w5.end.price >= ext_1618 * 0.98) or (
                    not is_bullish and w5.end.price <= ext_1618 * 1.02
                ):
                    signals += 1
        return signals >= 2

    def _check_b_wave_exit(self, df: pd.DataFrame, waves: dict[int, WaveSegment]) -> bool:
        """Rule 5: B-wave end exit/short."""
        if -1 not in waves or -2 not in waves:
            return False
        wa = waves[-1]
        wb = waves[-2]
        if wa.amplitude() <= 0:
            return False
        b_retracement = wb.amplitude() / wa.amplitude()
        if not any(abs(b_retracement - r) < 0.05 for r in self.b_retracement_ratios):
            return False
        if "volume" in df.columns and wb.end.index < len(df) and wa.end.index < len(df):
            a_vol = df["volume"].iloc[wa.end.index]
            b_vol = df["volume"].iloc[wb.end.index]
            if pd.notna(a_vol) and pd.notna(b_vol) and b_vol > a_vol:
                return False
        return True

    @staticmethod
    def _compute_macd_histogram(
        close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> pd.Series:
        ema_fast = close.ewm(span=fast).mean()
        ema_slow = close.ewm(span=slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        return macd_line - signal_line

    @staticmethod
    def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / period).mean()
        avg_loss = loss.ewm(alpha=1 / period).mean()
        rs = avg_gain / avg_loss.replace(0, float("inf"))
        return 100 - (100 / (1 + rs))
