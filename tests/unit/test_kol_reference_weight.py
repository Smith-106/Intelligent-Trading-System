"""KOL reference weight — size scale only, never direction."""

from __future__ import annotations

import json
from pathlib import Path

from quantflow.common.models import Direction, Portfolio, Signal
from quantflow.signal.position_sizer import PositionSizer
from quantflow.strategy.kol_signals.aggregator import ConsensusReport
from quantflow.strategy.kol_signals.models import SignalSide
from quantflow.strategy.kol_signals.reference_weight import (
    ReferenceWeightConfig,
    apply_reference_to_notional,
    build_reference_snapshot,
    load_consensus_reports,
    market_assessment,
    reference_multiplier,
)


def _rep(
    symbol: str,
    side: SignalSide,
    score: float,
    *,
    actionable: bool = True,
    n_sources: int = 3,
    end_ms: int = 2_000_000_000_000,
) -> ConsensusReport:
    return ConsensusReport(
        symbol=symbol,
        window_start_ms=end_ms - 3_600_000,
        window_end_ms=end_ms,
        side=side,
        score=score,
        long_weight=1.0 if side == SignalSide.LONG else 0.0,
        short_weight=1.0 if side == SignalSide.SHORT else 0.0,
        flat_weight=0.0,
        n_signals=n_sources,
        n_sources=n_sources,
        avg_confidence=0.8,
        signal_ids=["a", "b"],
        actionable=actionable,
        reason="ok" if actionable else "weak",
    )


def test_aligned_boosts_size() -> None:
    cfg = ReferenceWeightConfig(enabled=True, max_boost=0.15, max_cut=0.25)
    rep = _rep("BTC/USDT", SignalSide.LONG, 1.0)
    ref = reference_multiplier(
        "BTC/USDT",
        system_direction=Direction.LONG,
        reports=[rep],
        config=cfg,
        now_ms=rep.window_end_ms + 1000,
    )
    assert ref.aligned is True
    assert ref.multiplier == 1.15
    assert ref.assessment == "bullish"
    assert ref.reason == "kol_aligned_boost"


def test_opposed_cuts_size() -> None:
    cfg = ReferenceWeightConfig(enabled=True, max_boost=0.15, max_cut=0.25)
    rep = _rep("ETH/USDT", SignalSide.SHORT, 0.8)
    ref = reference_multiplier(
        "ETH/USDT",
        system_direction=1,  # long
        reports=[rep],
        config=cfg,
        now_ms=rep.window_end_ms + 1000,
    )
    assert ref.aligned is False
    assert ref.multiplier == round(1.0 - 0.25 * 0.8, 6)
    assert ref.assessment == "bearish"


def test_disabled_is_identity() -> None:
    ref = reference_multiplier(
        "BTC/USDT",
        system_direction=Direction.LONG,
        reports=[_rep("BTC/USDT", SignalSide.LONG, 1.0)],
        config=ReferenceWeightConfig(enabled=False),
    )
    assert ref.multiplier == 1.0
    assert ref.reason == "kol_reference_disabled"


def test_missing_or_weak_no_change() -> None:
    cfg = ReferenceWeightConfig(enabled=True)
    r1 = reference_multiplier("SOL/USDT", system_direction=1, reports=[], config=cfg)
    assert r1.multiplier == 1.0
    assert r1.reason == "no_kol_data"

    weak = _rep("SOL/USDT", SignalSide.LONG, 0.1, actionable=True)
    r2 = reference_multiplier(
        "SOL/USDT",
        system_direction=1,
        reports=[weak],
        config=cfg,
        now_ms=weak.window_end_ms + 1,
    )
    assert r2.multiplier == 1.0
    assert r2.reason == "weak_score"


def test_market_assessment_risk_on() -> None:
    reps = [
        _rep("BTC/USDT", SignalSide.LONG, 0.9),
        _rep("ETH/USDT", SignalSide.LONG, 0.7),
    ]
    m = market_assessment(reps)
    assert m.label == "risk-on"
    assert m.n_actionable == 2
    assert "BTC/USDT" in m.bullish_symbols


def test_load_consensus_and_snapshot(tmp_path: Path) -> None:
    payload = {
        "all": [
            {
                "symbol": "BTC/USDT",
                "window_start_ms": 1,
                "window_end_ms": 2_000_000_000_000,
                "side": "long",
                "score": 0.9,
                "long_weight": 1.0,
                "short_weight": 0.0,
                "flat_weight": 0.0,
                "n_signals": 2,
                "n_sources": 2,
                "avg_confidence": 0.8,
                "signal_ids": [],
                "actionable": True,
                "reason": "ok",
            }
        ]
    }
    p = tmp_path / "latest_consensus.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    reps = load_consensus_reports(p)
    assert len(reps) == 1
    snap = build_reference_snapshot(
        ["BTC/USDT"],
        system_directions={"BTC/USDT": "long"},
        reports=reps,
        config=ReferenceWeightConfig(enabled=True),
    )
    assert snap["symbols"]["BTC/USDT"]["multiplier"] > 1.0


def test_position_sizer_accepts_reference_multiplier() -> None:
    sizer = PositionSizer(method="fixed", fixed_pct=0.10, max_position_pct=0.5)
    sig = Signal(
        symbol="BTC/USDT",
        direction=Direction.LONG,
        strength=1.0,
        price=50_000.0,
        strategy_id="trend",
        timestamp=0,
    )
    port = Portfolio(cash=100_000.0, positions={})
    base = sizer.size(sig, port)
    boosted = sizer.size(sig, port, reference_multiplier=1.15)
    cut = sizer.size(sig, port, reference_multiplier=0.8)
    assert boosted > base
    assert cut < base
    ref = reference_multiplier(
        "BTC/USDT",
        system_direction=Direction.LONG,
        reports=[_rep("BTC/USDT", SignalSide.LONG, 1.0)],
        config=ReferenceWeightConfig(enabled=True),
        now_ms=2_000_000_001_000,
    )
    assert apply_reference_to_notional(base, ref) == round(base * 1.15, 2)
