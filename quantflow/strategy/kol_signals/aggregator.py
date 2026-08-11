"""Time-window consensus over multiple KOL signals."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from quantflow.strategy.kol_signals.models import KolSignal, SignalSide


@dataclass
class ConsensusReport:
    symbol: str
    window_start_ms: int
    window_end_ms: int
    side: SignalSide
    score: float  # net weighted score in [-1, 1]
    long_weight: float
    short_weight: float
    flat_weight: float
    n_signals: int
    n_sources: int
    avg_confidence: float
    signal_ids: list[str] = field(default_factory=list)
    actionable: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["side"] = self.side.value
        return d


def _side_sign(side: SignalSide) -> float:
    if side == SignalSide.LONG:
        return 1.0
    if side == SignalSide.SHORT:
        return -1.0
    return 0.0


def aggregate_consensus(
    signals: list[KolSignal],
    *,
    window_ms: int = 6 * 3600 * 1000,
    min_sources: int = 2,
    min_score: float = 0.35,
    min_confidence: float = 0.35,
    now_ms: int | None = None,
) -> list[ConsensusReport]:
    """Aggregate signals into per-symbol consensus reports.

    Parameters
    ----------
    window_ms
        Only signals within ``[now_ms - window_ms, now_ms]`` (or max created_at
        if now_ms omitted) are considered.
    min_sources
        Distinct source_id required for actionable=True.
    min_score
        |net weighted score| threshold for actionable.
    """
    if not signals:
        return []

    max_ts = max(s.created_at_ms for s in signals)
    end = int(now_ms if now_ms is not None else max_ts)
    start = end - int(window_ms)

    by_symbol: dict[str, list[KolSignal]] = defaultdict(list)
    for s in signals:
        if s.created_at_ms < start or s.created_at_ms > end:
            continue
        if s.confidence < min_confidence and s.side == SignalSide.UNKNOWN:
            continue
        if not s.symbol:
            continue
        by_symbol[s.symbol].append(s)

    reports: list[ConsensusReport] = []
    for symbol, rows in sorted(by_symbol.items()):
        long_w = short_w = flat_w = 0.0
        conf_sum = 0.0
        sources: set[str] = set()
        ids: list[str] = []
        for s in rows:
            w = max(0.0, float(s.weight)) * max(0.0, float(s.confidence))
            if s.side == SignalSide.LONG:
                long_w += w
            elif s.side == SignalSide.SHORT:
                short_w += w
            elif s.side == SignalSide.FLAT:
                flat_w += w
            sources.add(s.source_id)
            ids.append(s.signal_id)
            conf_sum += float(s.confidence)

        total = long_w + short_w + flat_w
        score = 0.0 if total <= 0 else (long_w - short_w) / total
        if abs(score) < 1e-9 and flat_w > long_w and flat_w > short_w:
            side = SignalSide.FLAT
        elif score > 0:
            side = SignalSide.LONG
        elif score < 0:
            side = SignalSide.SHORT
        else:
            side = SignalSide.UNKNOWN

        n_src = len(sources)
        avg_c = conf_sum / len(rows) if rows else 0.0
        actionable = (
            n_src >= min_sources
            and abs(score) >= min_score
            and side in (SignalSide.LONG, SignalSide.SHORT)
        )
        reason = "ok" if actionable else "below_threshold"
        if n_src < min_sources:
            reason = "insufficient_sources"
        elif abs(score) < min_score:
            reason = "weak_score"
        elif side not in (SignalSide.LONG, SignalSide.SHORT):
            reason = "no_directional_consensus"

        reports.append(
            ConsensusReport(
                symbol=symbol,
                window_start_ms=start,
                window_end_ms=end,
                side=side,
                score=round(score, 6),
                long_weight=round(long_w, 6),
                short_weight=round(short_w, 6),
                flat_weight=round(flat_w, 6),
                n_signals=len(rows),
                n_sources=n_src,
                avg_confidence=round(avg_c, 6),
                signal_ids=ids,
                actionable=actionable,
                reason=reason,
            )
        )

    reports.sort(key=lambda r: (r.actionable, abs(r.score), r.n_sources), reverse=True)
    return reports
