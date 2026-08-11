"""KOL consensus as **reference weight only** (never flips direction / auto-trade).

Use case (paid-member Discord KOLs):
  market assessment + live call consensus → scale position size slightly
  when your own strategy already has a direction.

Defaults are conservative:
  - missing / weak consensus → multiplier 1.0
  - agree with system side → modest boost (cap ``max_boost``)
  - disagree → modest cut (cap ``max_cut``)
  - never changes Signal.direction
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from quantflow.strategy.kol_signals.aggregator import ConsensusReport, aggregate_consensus
from quantflow.strategy.kol_signals.models import KolSignal, SignalSide
from quantflow.strategy.kol_signals.store import KolSignalStore

DEFAULT_CONSENSUS_PATH = Path("data/kol_signals/latest_consensus.json")


@dataclass(frozen=True)
class ReferenceWeightConfig:
    """How strongly KOL consensus may touch size (not direction)."""

    enabled: bool = False
    max_boost: float = 0.15  # +15% size when aligned
    max_cut: float = 0.25  # -25% size when opposed
    min_abs_score: float = 0.35
    require_actionable: bool = True
    # If system has no direction yet, still expose assessment but multiplier=1.0
    size_when_flat: float = 1.0
    # Stale consensus: ignore if older than this (ms); 0 = no staleness check
    max_age_ms: int = 6 * 3600 * 1000

    def clamp(self) -> ReferenceWeightConfig:
        return ReferenceWeightConfig(
            enabled=bool(self.enabled),
            max_boost=max(0.0, min(float(self.max_boost), 1.0)),
            max_cut=max(0.0, min(float(self.max_cut), 0.95)),
            min_abs_score=max(0.0, min(float(self.min_abs_score), 1.0)),
            require_actionable=bool(self.require_actionable),
            size_when_flat=max(0.0, float(self.size_when_flat)),
            max_age_ms=max(0, int(self.max_age_ms)),
        )


@dataclass
class SymbolReference:
    symbol: str
    multiplier: float
    kol_side: str
    score: float
    actionable: bool
    aligned: bool | None
    reason: str
    n_sources: int = 0
    assessment: str = "neutral"  # bullish | bearish | neutral | unavailable

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MarketAssessment:
    """Cross-symbol KOL bias snapshot (dashboard / log)."""

    as_of_ms: int
    n_symbols: int
    n_actionable: int
    bullish_symbols: list[str] = field(default_factory=list)
    bearish_symbols: list[str] = field(default_factory=list)
    net_bias: float = 0.0  # mean score of actionable, [-1, 1]
    label: str = "neutral"  # risk-on | risk-off | mixed | neutral | unavailable
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper().replace("-", "/")
    if not s:
        return ""
    if "/" not in s and s.endswith("USDT"):
        return f"{s[:-4]}/USDT"
    return s


def _direction_sign(direction: Any) -> int:
    """Map engine Direction / int / str → +1 long, -1 short, 0 flat/unknown."""
    if direction is None:
        return 0
    if isinstance(direction, (int, float)):
        v = int(direction)
        return 1 if v > 0 else (-1 if v < 0 else 0)
    # Enum with .value
    val = getattr(direction, "value", direction)
    if isinstance(val, (int, float)):
        v = int(val)
        return 1 if v > 0 else (-1 if v < 0 else 0)
    text = str(val).lower()
    if text in {"long", "buy", "1"}:
        return 1
    if text in {"short", "sell", "-1"}:
        return -1
    return 0


def _side_sign(side: SignalSide | str) -> int:
    if isinstance(side, SignalSide):
        s = side
    else:
        try:
            s = SignalSide(str(side))
        except ValueError:
            return 0
    if s == SignalSide.LONG:
        return 1
    if s == SignalSide.SHORT:
        return -1
    return 0


def load_consensus_reports(
    path: str | Path = DEFAULT_CONSENSUS_PATH,
) -> list[ConsensusReport]:
    """Load reports from ``latest_consensus.json`` (export of consensus CLI)."""
    p = Path(path)
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = raw.get("all") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    out: list[ConsensusReport] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            side = SignalSide(str(r.get("side", "unknown")))
        except ValueError:
            side = SignalSide.UNKNOWN
        out.append(
            ConsensusReport(
                symbol=str(r.get("symbol", "")),
                window_start_ms=int(r.get("window_start_ms") or 0),
                window_end_ms=int(r.get("window_end_ms") or 0),
                side=side,
                score=float(r.get("score") or 0.0),
                long_weight=float(r.get("long_weight") or 0.0),
                short_weight=float(r.get("short_weight") or 0.0),
                flat_weight=float(r.get("flat_weight") or 0.0),
                n_signals=int(r.get("n_signals") or 0),
                n_sources=int(r.get("n_sources") or 0),
                avg_confidence=float(r.get("avg_confidence") or 0.0),
                signal_ids=list(r.get("signal_ids") or []),
                actionable=bool(r.get("actionable")),
                reason=str(r.get("reason") or ""),
            )
        )
    return out


def reports_from_store(
    store: KolSignalStore | None = None,
    *,
    window_ms: int = 6 * 3600 * 1000,
    min_sources: int = 2,
    min_score: float = 0.35,
    min_confidence: float = 0.35,
) -> list[ConsensusReport]:
    """Recompute consensus live from JSONL store (no file dependency)."""
    st = store or KolSignalStore()
    signals: list[KolSignal] = st.load_signals()
    return aggregate_consensus(
        signals,
        window_ms=window_ms,
        min_sources=min_sources,
        min_score=min_score,
        min_confidence=min_confidence,
    )


def _index_by_symbol(reports: list[ConsensusReport]) -> dict[str, ConsensusReport]:
    idx: dict[str, ConsensusReport] = {}
    for r in reports:
        key = _normalize_symbol(r.symbol)
        if not key:
            continue
        # Prefer actionable / higher |score|
        prev = idx.get(key)
        if prev is None:
            idx[key] = r
            continue
        if (r.actionable and not prev.actionable) or (
            r.actionable == prev.actionable and abs(r.score) > abs(prev.score)
        ):
            idx[key] = r
    return idx


def market_assessment(
    reports: list[ConsensusReport],
    *,
    as_of_ms: int | None = None,
) -> MarketAssessment:
    """Aggregate multi-symbol KOL bias for UI / logs (not a trade signal)."""
    now = int(as_of_ms if as_of_ms is not None else time.time() * 1000)
    if not reports:
        return MarketAssessment(
            as_of_ms=now,
            n_symbols=0,
            n_actionable=0,
            label="unavailable",
            notes=["no_consensus_reports"],
        )
    actionable = [r for r in reports if r.actionable]
    bull = [_normalize_symbol(r.symbol) for r in actionable if r.side == SignalSide.LONG]
    bear = [_normalize_symbol(r.symbol) for r in actionable if r.side == SignalSide.SHORT]
    scores = [r.score for r in actionable]
    net = float(sum(scores) / len(scores)) if scores else 0.0
    if not actionable:
        label = "neutral"
        notes = ["no_actionable_consensus"]
    elif net >= 0.25 and len(bull) >= len(bear):
        label = "risk-on"
        notes = []
    elif net <= -0.25 and len(bear) >= len(bull):
        label = "risk-off"
        notes = []
    elif bull and bear:
        label = "mixed"
        notes = ["split_actionable"]
    else:
        label = "neutral"
        notes = []
    return MarketAssessment(
        as_of_ms=now,
        n_symbols=len({_normalize_symbol(r.symbol) for r in reports}),
        n_actionable=len(actionable),
        bullish_symbols=sorted(set(bull)),
        bearish_symbols=sorted(set(bear)),
        net_bias=round(net, 6),
        label=label,
        notes=notes,
    )


def reference_multiplier(
    symbol: str,
    *,
    system_direction: Any = None,
    reports: list[ConsensusReport] | None = None,
    consensus_path: str | Path = DEFAULT_CONSENSUS_PATH,
    config: ReferenceWeightConfig | None = None,
    now_ms: int | None = None,
) -> SymbolReference:
    """Return size multiplier in ``[1-max_cut, 1+max_boost]`` for one symbol."""
    cfg = (config or ReferenceWeightConfig()).clamp()
    sym = _normalize_symbol(symbol)
    if not cfg.enabled:
        return SymbolReference(
            symbol=sym,
            multiplier=1.0,
            kol_side="unknown",
            score=0.0,
            actionable=False,
            aligned=None,
            reason="kol_reference_disabled",
            assessment="unavailable",
        )

    reps = reports if reports is not None else load_consensus_reports(consensus_path)
    idx = _index_by_symbol(reps)
    rep = idx.get(sym)
    if rep is None:
        return SymbolReference(
            symbol=sym,
            multiplier=1.0,
            kol_side="unknown",
            score=0.0,
            actionable=False,
            aligned=None,
            reason="no_kol_data",
            assessment="unavailable",
        )

    now = int(now_ms if now_ms is not None else time.time() * 1000)
    if cfg.max_age_ms > 0 and rep.window_end_ms > 0:
        age = now - int(rep.window_end_ms)
        if age > cfg.max_age_ms:
            return SymbolReference(
                symbol=sym,
                multiplier=1.0,
                kol_side=rep.side.value,
                score=rep.score,
                actionable=False,
                aligned=None,
                reason="stale_consensus",
                n_sources=rep.n_sources,
                assessment="unavailable",
            )

    if cfg.require_actionable and not rep.actionable:
        return SymbolReference(
            symbol=sym,
            multiplier=1.0,
            kol_side=rep.side.value,
            score=rep.score,
            actionable=False,
            aligned=None,
            reason=f"not_actionable:{rep.reason}",
            n_sources=rep.n_sources,
            assessment="neutral",
        )

    if abs(rep.score) < cfg.min_abs_score:
        return SymbolReference(
            symbol=sym,
            multiplier=1.0,
            kol_side=rep.side.value,
            score=rep.score,
            actionable=rep.actionable,
            aligned=None,
            reason="weak_score",
            n_sources=rep.n_sources,
            assessment="neutral",
        )

    kol_sign = _side_sign(rep.side)
    assessment = "bullish" if kol_sign > 0 else ("bearish" if kol_sign < 0 else "neutral")
    sys_sign = _direction_sign(system_direction)

    if sys_sign == 0 or kol_sign == 0:
        return SymbolReference(
            symbol=sym,
            multiplier=float(cfg.size_when_flat),
            kol_side=rep.side.value,
            score=rep.score,
            actionable=rep.actionable,
            aligned=None,
            reason="no_system_direction_or_kol_flat",
            n_sources=rep.n_sources,
            assessment=assessment,
        )

    aligned = (sys_sign * kol_sign) > 0
    intensity = min(1.0, abs(rep.score))
    if aligned:
        mult = 1.0 + cfg.max_boost * intensity
        reason = "kol_aligned_boost"
    else:
        mult = 1.0 - cfg.max_cut * intensity
        reason = "kol_opposed_cut"

    mult = max(1.0 - cfg.max_cut, min(1.0 + cfg.max_boost, mult))
    return SymbolReference(
        symbol=sym,
        multiplier=round(mult, 6),
        kol_side=rep.side.value,
        score=rep.score,
        actionable=rep.actionable,
        aligned=aligned,
        reason=reason,
        n_sources=rep.n_sources,
        assessment=assessment,
    )


def apply_reference_to_notional(
    notional: float,
    ref: SymbolReference,
) -> float:
    """Scale a computed order notional by KOL reference (floor at 0)."""
    if notional <= 0:
        return 0.0
    return round(max(0.0, float(notional) * float(ref.multiplier)), 2)


def build_reference_snapshot(
    symbols: list[str],
    *,
    system_directions: dict[str, Any] | None = None,
    reports: list[ConsensusReport] | None = None,
    consensus_path: str | Path = DEFAULT_CONSENSUS_PATH,
    config: ReferenceWeightConfig | None = None,
) -> dict[str, Any]:
    """Batch snapshot for CLI / monitoring."""
    cfg = (config or ReferenceWeightConfig(enabled=True)).clamp()
    reps = reports if reports is not None else load_consensus_reports(consensus_path)
    dirs = system_directions or {}
    per: dict[str, Any] = {}
    for sym in symbols:
        key = _normalize_symbol(sym)
        per[key] = reference_multiplier(
            key,
            system_direction=dirs.get(key) or dirs.get(sym),
            reports=reps,
            config=cfg,
        ).to_dict()
    assess = market_assessment(reps)
    return {
        "config": asdict(cfg),
        "market_assessment": assess.to_dict(),
        "symbols": per,
        "note": "reference weight only — does not place or reverse orders",
    }
