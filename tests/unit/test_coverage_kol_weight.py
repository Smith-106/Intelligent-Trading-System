"""Coverage completion for KOL reference-weight module.

Targets remaining uncovered lines/branches in reference_weight.py:
- _normalize_symbol empty/raw-USDT, _direction_sign None/enum/str paths,
  _side_sign invalid string + FLAT, load_consensus_reports failure paths,
  reports_from_store, _index_by_symbol replace logic, market_assessment
  unavailable/neutral/risk-off/mixed/else-neutral, reference_multiplier
  stale/not-actionable/no-direction paths, apply_reference_to_notional floor.

Pure logic; no network, no vectorbt.
"""

from __future__ import annotations

import json
from pathlib import Path

from quantflow.strategy.kol_signals.aggregator import ConsensusReport
from quantflow.strategy.kol_signals.models import KolSignal, SignalSide
from quantflow.strategy.kol_signals.reference_weight import (
    ReferenceWeightConfig,
    _direction_sign,
    _index_by_symbol,
    _normalize_symbol,
    _side_sign,
    apply_reference_to_notional,
    load_consensus_reports,
    market_assessment,
    reference_multiplier,
    reports_from_store,
)
from quantflow.strategy.kol_signals.store import KolSignalStore


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


class _Valued:
    """Object exposing a .value int (StrEnum-like, but not an int)."""

    value: object

    def __init__(self, value: object) -> None:
        self.value = value


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_normalize_symbol_empty(self) -> None:
        assert _normalize_symbol("") == ""
        assert _normalize_symbol("   ") == ""

    def test_normalize_symbol_raw_usdt(self) -> None:
        assert _normalize_symbol("btcusdt") == "BTC/USDT"

    def test_direction_sign_none(self) -> None:
        assert _direction_sign(None) == 0

    def test_direction_sign_valued_enum(self) -> None:
        assert _direction_sign(_Valued(1)) == 1
        assert _direction_sign(_Valued(-1)) == -1
        assert _direction_sign(_Valued(0)) == 0

    def test_direction_sign_strings(self) -> None:
        assert _direction_sign("long") == 1
        assert _direction_sign("buy") == 1
        assert _direction_sign("short") == -1
        assert _direction_sign("sell") == -1
        assert _direction_sign("maybe") == 0

    def test_side_sign_variants(self) -> None:
        assert _side_sign(SignalSide.LONG) == 1
        assert _side_sign(SignalSide.SHORT) == -1
        assert _side_sign(SignalSide.FLAT) == 0
        assert _side_sign("long") == 1
        assert _side_sign("bogus") == 0


# ---------------------------------------------------------------------------
# load_consensus_reports failure paths
# ---------------------------------------------------------------------------


class TestLoadConsensusReports:
    def test_missing_file(self, tmp_path: Path) -> None:
        assert load_consensus_reports(tmp_path / "nope.json") == []

    def test_invalid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        assert load_consensus_reports(p) == []

    def test_rows_not_list(self, tmp_path: Path) -> None:
        p = tmp_path / "r.json"
        p.write_text(json.dumps({"no_all_key": 1}), encoding="utf-8")
        assert load_consensus_reports(p) == []

    def test_skips_non_dict_rows_and_bad_side(self, tmp_path: Path) -> None:
        p = tmp_path / "r.json"
        p.write_text(
            json.dumps(
                {
                    "all": [
                        "not-a-dict",
                        {"symbol": "ETH/USDT", "side": "bogus", "score": "0.5"},
                        {"symbol": "SOL/USDT", "side": "short", "score": 0.7},
                    ]
                }
            ),
            encoding="utf-8",
        )
        out = load_consensus_reports(p)
        assert len(out) == 2
        assert out[0].side == SignalSide.UNKNOWN
        assert out[1].side == SignalSide.SHORT


# ---------------------------------------------------------------------------
# reports_from_store
# ---------------------------------------------------------------------------


class TestReportsFromStore:
    def test_recompute_from_store(self, tmp_path: Path) -> None:
        store = KolSignalStore(tmp_path)
        store.append_signal(
            KolSignal(
                signal_id="a",
                source_id="k1",
                platform="discord",
                channel_id="c",
                message_id="m",
                author="x",
                created_at_ms=1_700_000_000_000,
                raw_text="long",
                side=SignalSide.LONG,
                symbol="BTC/USDT",
                confidence=0.8,
            )
        )
        out = reports_from_store(store, window_ms=3_600_000, min_sources=1)
        assert len(out) == 1
        assert out[0].symbol == "BTC/USDT"

    def test_reports_from_store_default(self, tmp_path: Path, monkeypatch) -> None:
        st = KolSignalStore(tmp_path / "empty")
        monkeypatch.setattr(
            "quantflow.strategy.kol_signals.reference_weight.KolSignalStore",
            lambda: st,
        )
        assert reports_from_store() == []


# ---------------------------------------------------------------------------
# _index_by_symbol
# ---------------------------------------------------------------------------


class TestIndexBySymbol:
    def test_skips_empty_symbol_and_prefers_actionable(self) -> None:
        reports = [
            ConsensusReport(
                symbol="",
                window_start_ms=1,
                window_end_ms=2,
                side=SignalSide.LONG,
                score=0.5,
                long_weight=1.0,
                short_weight=0.0,
                flat_weight=0.0,
                n_signals=1,
                n_sources=1,
                avg_confidence=0.8,
            ),
            _rep("BTC/USDT", SignalSide.LONG, 0.3, actionable=False),
            _rep("BTC/USDT", SignalSide.LONG, 0.9, actionable=True),
            _rep("ETH/USDT", SignalSide.SHORT, 0.5),
            _rep("ETH/USDT", SignalSide.SHORT, 0.8),
        ]
        idx = _index_by_symbol(reports)
        assert idx["BTC/USDT"].score == 0.9  # actionable replaced weak
        assert idx["ETH/USDT"].score == 0.8  # higher |score| replaced

    def test_keeps_prev_when_not_better(self) -> None:
        # same actionability but lower |score| -> replace condition False
        reports = [
            _rep("BTC/USDT", SignalSide.LONG, 0.9, actionable=True),
            _rep("BTC/USDT", SignalSide.LONG, 0.5, actionable=True),
        ]
        idx = _index_by_symbol(reports)
        assert idx["BTC/USDT"].score == 0.9


# ---------------------------------------------------------------------------
# market_assessment labels
# ---------------------------------------------------------------------------


class TestMarketAssessment:
    def test_no_reports_unavailable(self) -> None:
        m = market_assessment([], as_of_ms=123)
        assert m.label == "unavailable"
        assert m.notes == ["no_consensus_reports"]

    def test_no_actionable_neutral(self) -> None:
        reps = [_rep("BTC/USDT", SignalSide.LONG, 0.9, actionable=False)]
        m = market_assessment(reps, as_of_ms=123)
        assert m.label == "neutral"
        assert m.notes == ["no_actionable_consensus"]
        assert m.n_actionable == 0

    def test_risk_off(self) -> None:
        reps = [
            _rep("BTC/USDT", SignalSide.SHORT, -0.9),
            _rep("ETH/USDT", SignalSide.SHORT, -0.7),
        ]
        m = market_assessment(reps, as_of_ms=123)
        assert m.label == "risk-off"
        assert len(m.bullish_symbols) == 0
        assert len(m.bearish_symbols) == 2

    def test_mixed(self) -> None:
        reps = [
            _rep("BTC/USDT", SignalSide.LONG, 0.9),
            _rep("ETH/USDT", SignalSide.SHORT, -0.9),
        ]
        m = market_assessment(reps, as_of_ms=123)
        assert m.label == "mixed"
        assert m.notes == ["split_actionable"]

    def test_else_neutral_all_bulls_low_net(self) -> None:
        # all actionable bulls but net < 0.25 -> else branch neutral
        reps = [
            _rep("BTC/USDT", SignalSide.LONG, 0.2),
            _rep("ETH/USDT", SignalSide.LONG, 0.1),
        ]
        m = market_assessment(reps, as_of_ms=123)
        assert m.label == "neutral"
        assert m.notes == []


# ---------------------------------------------------------------------------
# reference_multiplier remaining paths
# ---------------------------------------------------------------------------


class TestReferenceMultiplier:
    def test_stale_consensus(self) -> None:
        cfg = ReferenceWeightConfig(enabled=True, max_age_ms=3_600_000)
        rep = _rep("BTC/USDT", SignalSide.LONG, 0.9, end_ms=1_000_000_000)
        ref = reference_multiplier(
            "BTC/USDT",
            system_direction=1,
            reports=[rep],
            config=cfg,
            now_ms=1_000_000_000 + 100_000_000,  # 100s > 1h
        )
        assert ref.reason == "stale_consensus"
        assert ref.multiplier == 1.0
        assert ref.actionable is False

    def test_no_staleness_check_when_max_age_zero(self) -> None:
        cfg = ReferenceWeightConfig(enabled=True, max_age_ms=0)
        rep = _rep("BTC/USDT", SignalSide.LONG, 0.9, end_ms=1_000_000_000)
        ref = reference_multiplier(
            "BTC/USDT",
            system_direction=1,
            reports=[rep],
            config=cfg,
            now_ms=1_000_000_000 + 100_000_000,
        )
        assert ref.reason == "kol_aligned_boost"
        assert ref.aligned is True

    def test_not_actionable(self) -> None:
        cfg = ReferenceWeightConfig(enabled=True, require_actionable=True)
        rep = _rep("BTC/USDT", SignalSide.LONG, 0.9, actionable=False)
        ref = reference_multiplier(
            "BTC/USDT",
            system_direction=1,
            reports=[rep],
            config=cfg,
            now_ms=rep.window_end_ms + 1000,
        )
        assert ref.reason == "not_actionable:weak"
        assert ref.multiplier == 1.0

    def test_no_system_direction_uses_flat_size(self) -> None:
        cfg = ReferenceWeightConfig(enabled=True, size_when_flat=1.0)
        rep = _rep("BTC/USDT", SignalSide.LONG, 0.9)
        ref = reference_multiplier(
            "BTC/USDT",
            system_direction=None,
            reports=[rep],
            config=cfg,
            now_ms=rep.window_end_ms + 1000,
        )
        assert ref.reason == "no_system_direction_or_kol_flat"
        assert ref.multiplier == 1.0

    def test_kol_flat_with_system_direction(self) -> None:
        # min_abs_score=0 so flat report (score 0) passes the weak_score gate
        cfg = ReferenceWeightConfig(enabled=True, min_abs_score=0.0)
        rep = _rep("BTC/USDT", SignalSide.FLAT, 0.0)
        ref = reference_multiplier(
            "BTC/USDT",
            system_direction=1,
            reports=[rep],
            config=cfg,
            now_ms=rep.window_end_ms + 1000,
        )
        assert ref.reason == "no_system_direction_or_kol_flat"
        assert ref.multiplier == float(cfg.size_when_flat)


# ---------------------------------------------------------------------------
# apply_reference_to_notional
# ---------------------------------------------------------------------------


class TestApplyNotional:
    def test_non_positive_notional_returns_zero(self) -> None:
        ref = reference_multiplier("BTC/USDT", config=ReferenceWeightConfig(enabled=False))
        assert apply_reference_to_notional(0.0, ref) == 0.0
        assert apply_reference_to_notional(-10.0, ref) == 0.0
