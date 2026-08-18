"""Coverage completion for KOL core modules (parser/models/registry/store/aggregator).

Targets remaining uncovered lines/branches in:
- parser: _normalize_symbol quote-less branches, extract_symbol no-match,
  extract_side conflict/flat/no-match, extract_levels without SL,
  parse_trade_text note paths (side_unknown/symbol_unknown/media_heavy)
- models: to_dict on KolSource/AttachmentMeta, from_dict bad side + non-dict
  attachment, _opt_float failure
- registry: missing file, non-list items, non-dict rows, missing source_id,
  platform mismatch, wildcard/prefix channel match, registry_to_dict
- store: append_consensus, blank lines, corrupt JSONL, limit slicing
- aggregator: empty input, filtered signals, SHORT/FLAT weights, flat-side
  report, UNKNOWN-side report, reason classification branches, to_dict

Pure logic; no network, no OCR backends, no vectorbt.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantflow.strategy.kol_signals import aggregator as agg_mod
from quantflow.strategy.kol_signals.aggregator import ConsensusReport, aggregate_consensus
from quantflow.strategy.kol_signals.models import (
    AttachmentMeta,
    KolSignal,
    KolSource,
    SignalSide,
)
from quantflow.strategy.kol_signals.parser import (
    _normalize_symbol,
    extract_levels,
    extract_side,
    extract_symbol,
    parse_trade_text,
)
from quantflow.strategy.kol_signals.registry import (
    load_kol_registry,
    registry_to_dict,
    source_by_channel,
)
from quantflow.strategy.kol_signals.store import KolSignalStore


def _sig(
    symbol: str,
    side: SignalSide,
    *,
    source_id: str = "kol_a",
    confidence: float = 0.8,
    weight: float = 1.0,
    ts: int = 1_700_000_000_000,
    signal_id: str | None = None,
) -> KolSignal:
    return KolSignal(
        signal_id=signal_id or f"{source_id}-{symbol}-{side.value}",
        source_id=source_id,
        platform="discord",
        channel_id="ch1",
        message_id=f"m-{source_id}-{side.value}",
        author="a",
        created_at_ms=ts,
        raw_text=f"{side.value} {symbol}",
        side=side,
        symbol=symbol,
        confidence=confidence,
        weight=weight,
    )


# ---------------------------------------------------------------------------
# parser._normalize_symbol quote-less branches
# ---------------------------------------------------------------------------


class TestNormalizeSymbol:
    def test_usdt_suffix(self) -> None:
        assert _normalize_symbol("BTCUSDT") == "BTC/USDT"

    def test_usd_suffix(self) -> None:
        assert _normalize_symbol("BTCUSD") == "BTC/USDT"

    def test_usdc_suffix(self) -> None:
        assert _normalize_symbol("BTCUSDC") == "BTC/USDC"

    def test_perp_suffix(self) -> None:
        assert _normalize_symbol("BTCPERP") == "BTC/USDT"

    def test_short_bare_base(self) -> None:
        assert _normalize_symbol("eth") == "ETH/USDT"

    def test_long_bare_base_unchanged(self) -> None:
        assert _normalize_symbol("AVERYLONGBASENAME") == "AVERYLONGBASENAME"

    def test_with_quote(self) -> None:
        # quote path appends normalized quote to the stripped base verbatim
        assert _normalize_symbol("btc-usdt", "USDT") == "BTCUSDT/USDT"
        assert _normalize_symbol("btc", "PERP") == "BTC/USDT"


# ---------------------------------------------------------------------------
# parser.extract_symbol / extract_side / extract_levels
# ---------------------------------------------------------------------------


class TestExtractSymbol:
    def test_cn_symbol_lowercase_scan(self) -> None:
        # "sol" key matched via text.lower() when input is uppercase
        sym, conf = extract_symbol("SOL breakout")
        assert sym == "SOL/USDT"
        assert conf == 0.7

    def test_quote_pair_pattern(self) -> None:
        sym, conf = extract_symbol("long BTC/USDT")
        assert sym == "BTC/USDT"
        assert conf == 0.9

    def test_dollar_pattern(self) -> None:
        sym, conf = extract_symbol("buy $DOGE now")
        assert sym == "DOGE/USDT"
        assert conf == 0.75

    def test_no_symbol(self) -> None:
        assert extract_symbol("no tickers here") == ("", 0.0)


class TestExtractSide:
    def test_conflict_long_short(self) -> None:
        assert extract_side("long then short") == (SignalSide.UNKNOWN, 0.2)

    def test_flat_only(self) -> None:
        assert extract_side("close everything now") == (SignalSide.FLAT, 0.7)

    def test_short_only(self) -> None:
        assert extract_side("short ETH now") == (SignalSide.SHORT, 0.85)

    def test_no_side(self) -> None:
        assert extract_side("what do you think of the market") == (SignalSide.UNKNOWN, 0.0)


class TestExtractLevels:
    def test_entry_without_sl(self) -> None:
        # entry present, SL missing -> SL if-branch not taken
        out = extract_levels("entry: 1000")
        assert out == {"entry": 1000.0, "stop_loss": None, "take_profit": []}

    def test_all_present(self) -> None:
        out = extract_levels("entry 1000 SL 900 TP 1100 TP2 1200")
        assert out["stop_loss"] == 900.0
        assert out["take_profit"] == [1100.0, 1200.0]


# ---------------------------------------------------------------------------
# parser.parse_trade_text note paths
# ---------------------------------------------------------------------------


class TestParseTradeTextNotes:
    def test_side_and_symbol_unknown_notes(self) -> None:
        p = parse_trade_text("随便聊聊市场")
        assert p["side"] == SignalSide.UNKNOWN
        assert p["confidence"] == 0.0
        assert "side_unknown" in p["parse_notes"]
        assert "symbol_unknown" in p["parse_notes"]

    def test_media_heavy_note(self) -> None:
        # conf < 0.3 and contains http/chart -> likely_media_heavy
        p = parse_trade_text("see http://example.com/chart.png for details")
        assert "likely_media_heavy" in p["parse_notes"]
        assert p["confidence"] == 0.0

    def test_no_levels_but_direction(self) -> None:
        # direction present (conf 0.3825), no levels -> levels if-False branch
        p = parse_trade_text("long BTC")
        assert p["side"] == SignalSide.LONG
        assert p["entry"] is None
        assert "levels_present" not in p["parse_notes"]
        assert p["confidence"] > 0.3

    def test_tf_note(self) -> None:
        p = parse_trade_text("long BTC/USDT 4h")
        assert "tf=4h" in p["parse_notes"]


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


class TestModels:
    def test_kol_source_to_dict(self) -> None:
        src = KolSource(
            source_id="s1",
            display_name="Alpha",
            platform="discord",
            channel_ids=["c1"],
            weight=1.5,
            tags=["cn"],
            enabled=True,
            notes="note",
        )
        d = src.to_dict()
        assert d["source_id"] == "s1"
        assert d["weight"] == 1.5

    def test_attachment_meta_to_dict(self) -> None:
        a = AttachmentMeta(url="u", local_path="p", ocr_text="t", is_chart_likely=True)
        d = a.to_dict()
        assert d["url"] == "u"
        assert d["is_chart_likely"] is True

    def test_from_dict_invalid_side(self) -> None:
        s = KolSignal.from_dict({"side": "bogus_side", "signal_id": "x"})
        assert s.side == SignalSide.UNKNOWN

    def test_from_dict_with_attachment_objects(self) -> None:
        att = AttachmentMeta(url="u")
        s = KolSignal.from_dict({"side": "long", "attachments": [att]})
        assert s.attachments == [att]

    def test_from_dict_full_roundtrip(self) -> None:
        data = {
            "signal_id": "s1",
            "source_id": "src",
            "platform": "discord",
            "channel_id": "ch",
            "message_id": "m",
            "author": "a",
            "created_at_ms": 123,
            "raw_text": "long",
            "side": "short",
            "symbol": "ETH/USDT",
            "entry": "3000",
            "stop_loss": "",
            "take_profit": [3200.0, None, 3400.0],
            "timeframe": "1h",
            "confidence": "0.9",
            "weight": "1.2",
            "attachments": [{"url": "u", "filename": "f.png"}],
            "parse_notes": ["n1"],
            "meta": {"k": "v"},
        }
        s = KolSignal.from_dict(data)
        assert s.side == SignalSide.SHORT
        assert s.entry == 3000.0
        assert s.stop_loss is None
        assert s.take_profit == [3200.0, 3400.0]
        assert s.meta == {"k": "v"}
        assert s.attachments[0].filename == "f.png"

    def test_opt_float_invalid(self) -> None:
        from quantflow.strategy.kol_signals.models import _opt_float

        assert _opt_float("not-a-number") is None
        assert _opt_float(1.5) == 1.5
        assert _opt_float("") is None


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert load_kol_registry(tmp_path / "nope.yaml") == []

    def test_dict_without_sources_returns_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "reg.yaml"
        p.write_text(json.dumps({"other": 1}), encoding="utf-8")
        assert load_kol_registry(p) == []

    def test_raw_list_shape(self, tmp_path: Path) -> None:
        p = tmp_path / "reg.yaml"
        p.write_text(json.dumps([{"source_id": "a"}]), encoding="utf-8")
        out = load_kol_registry(p)
        assert len(out) == 1
        assert out[0].source_id == "a"

    def test_skips_non_dict_and_empty_id(self, tmp_path: Path) -> None:
        p = tmp_path / "reg.yaml"
        p.write_text(
            json.dumps(
                {
                    "sources": [
                        "not-a-dict",
                        {"display_name": "no id"},
                        {"source_id": "  "},
                        {
                            "source_id": "ok",
                            "name": "Display",
                            "platform": "telegram",
                            "channel_ids": ["c1", "c2"],
                            "weight": 2.0,
                            "tags": ["t1"],
                            "enabled": False,
                            "notes": "n",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        out = load_kol_registry(p)
        assert len(out) == 1
        assert out[0].display_name == "Display"
        assert out[0].platform == "telegram"
        assert out[0].channel_ids == ["c1", "c2"]
        assert out[0].weight == 2.0
        assert out[0].enabled is False

    def test_source_by_channel_variants(self) -> None:
        srcs = [
            KolSource(source_id="disabled", channel_ids=["x1"], enabled=False),
            KolSource(source_id="other", channel_ids=["x2"], platform="telegram"),
            KolSource(source_id="match", channel_ids=["x3", "x4"]),
        ]
        assert source_by_channel(srcs, "x3").source_id == "match"
        assert source_by_channel(srcs, "x4").source_id == "match"
        assert source_by_channel(srcs, "x1") is None  # disabled
        assert source_by_channel(srcs, "x2") is None  # platform mismatch
        assert source_by_channel(srcs, "zzz", platform="telegram") is None
        wild = [KolSource(source_id="wild", channel_ids=["*"])]
        assert source_by_channel(wild, "anything").source_id == "wild"

    def test_registry_to_dict(self) -> None:
        d = registry_to_dict([KolSource(source_id="a")])
        assert d["sources"][0]["source_id"] == "a"


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------


class TestStore:
    def _seed(self, tmp_path: Path) -> KolSignalStore:
        store = KolSignalStore(tmp_path)
        store.append_signal(_sig("BTC/USDT", SignalSide.LONG, signal_id="s1"))
        store.append_signal(_sig("ETH/USDT", SignalSide.SHORT, signal_id="s2"))
        return store

    def test_append_consensus(self, tmp_path: Path) -> None:
        store = KolSignalStore(tmp_path)
        store.append_consensus([])  # empty -> early return
        store.append_consensus([{"symbol": "BTC/USDT", "score": 0.5}])
        lines = (tmp_path / "consensus.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["symbol"] == "BTC/USDT"

    def test_load_signals_skips_blank_and_corrupt(self, tmp_path: Path) -> None:
        store = self._seed(tmp_path)
        with store.signals_path.open("a", encoding="utf-8") as f:
            f.write("\n")
            f.write("{not-json}\n")
        rows = store.load_signals()
        assert len(rows) == 2

    def test_load_signals_limit(self, tmp_path: Path) -> None:
        store = self._seed(tmp_path)
        rows = store.load_signals(limit=1)
        assert len(rows) == 1
        assert rows[0].signal_id == "s2"
        # Python slice quirk: rows[-0:] == all rows (code uses >= 0)
        assert len(store.load_signals(limit=0)) == 2

    def test_known_ids_and_dedupe_key(self, tmp_path: Path) -> None:
        store = self._seed(tmp_path)
        known = store.known_message_ids()
        assert store.dedupe_key("discord", "ch1", "m-kol_a-long") in known


# ---------------------------------------------------------------------------
# aggregator
# ---------------------------------------------------------------------------


class TestAggregator:
    def test_consensus_report_to_dict(self) -> None:
        rep = ConsensusReport(
            symbol="BTC/USDT",
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
        )
        d = rep.to_dict()
        assert d["side"] == "long"

    def test_side_sign_helper(self) -> None:
        assert agg_mod._side_sign(SignalSide.LONG) == 1.0
        assert agg_mod._side_sign(SignalSide.SHORT) == -1.0
        assert agg_mod._side_sign(SignalSide.FLAT) == 0.0

    def test_empty_signals(self) -> None:
        assert aggregate_consensus([]) == []

    def test_filters_out_of_window_unknown_and_blank_symbol(self) -> None:
        now = 1_700_000_000_000
        signals = [
            _sig("BTC/USDT", SignalSide.LONG, ts=now - 100_000_000),  # too old
            _sig("ETH/USDT", SignalSide.UNKNOWN, confidence=0.1, ts=now),  # low-conf unknown
            _sig("", SignalSide.LONG, ts=now),  # no symbol
            _sig("SOL/USDT", SignalSide.LONG, ts=now, source_id="k1", signal_id="keep"),
        ]
        reports = aggregate_consensus(signals, window_ms=3600_000, min_sources=1, now_ms=now)
        assert [r.symbol for r in reports] == ["SOL/USDT"]

    def test_short_and_flat_weights_and_reasons(self) -> None:
        now = 1_700_000_000_000
        # balanced LONG+SHORT cancel (score 0) while FLAT dominates -> FLAT
        signals = [
            _sig("BTC/USDT", SignalSide.LONG, source_id="k1", ts=now),
            _sig("BTC/USDT", SignalSide.SHORT, source_id="k2", ts=now),
            _sig("BTC/USDT", SignalSide.FLAT, source_id="k3", ts=now, weight=2.0),
        ]
        reports = aggregate_consensus(
            signals, window_ms=3600_000, min_sources=2, min_score=0.0, now_ms=now
        )
        rep = reports[0]
        assert rep.side == SignalSide.FLAT
        assert rep.short_weight > 0
        assert rep.flat_weight > 0
        assert rep.reason == "no_directional_consensus"
        assert rep.actionable is False

    def test_unknown_only_report(self) -> None:
        now = 1_700_000_000_000
        signals = [
            _sig("BTC/USDT", SignalSide.UNKNOWN, confidence=0.9, source_id="k1", ts=now),
            _sig("BTC/USDT", SignalSide.UNKNOWN, confidence=0.9, source_id="k2", ts=now),
        ]
        reports = aggregate_consensus(
            signals, window_ms=3600_000, min_sources=2, min_score=0.0, now_ms=now
        )
        assert reports[0].side == SignalSide.UNKNOWN
        # score is exactly 0 and min_score is 0 -> skips weak_score, falls to
        # no_directional_consensus because side is not LONG/SHORT
        assert reports[0].reason == "no_directional_consensus"

    def test_insufficient_sources_reason(self) -> None:
        now = 1_700_000_000_000
        signals = [_sig("BTC/USDT", SignalSide.LONG, source_id="k1", ts=now)]
        reports = aggregate_consensus(
            signals, window_ms=3600_000, min_sources=2, min_score=0.1, now_ms=now
        )
        assert reports[0].reason == "insufficient_sources"
        assert reports[0].actionable is False

    def test_weak_score_reason(self) -> None:
        now = 1_700_000_000_000
        signals = [
            _sig("BTC/USDT", SignalSide.LONG, source_id="k1", ts=now),
            _sig("BTC/USDT", SignalSide.SHORT, source_id="k2", ts=now),
        ]
        # two directional signals cancel -> score 0 < min_score 0.2
        reports = aggregate_consensus(
            signals, window_ms=3600_000, min_sources=2, min_score=0.2, now_ms=now
        )
        assert reports[0].side == SignalSide.UNKNOWN
        assert reports[0].reason == "weak_score"

    def test_actionable_ok_reason_and_sort(self) -> None:
        now = 1_700_000_000_000
        signals = [
            _sig("BTC/USDT", SignalSide.LONG, source_id="k1", ts=now, weight=2.0),
            _sig("BTC/USDT", SignalSide.LONG, source_id="k2", ts=now),
            _sig("ETH/USDT", SignalSide.SHORT, source_id="k3", ts=now),
            _sig("ETH/USDT", SignalSide.SHORT, source_id="k4", ts=now, weight=0.5),
        ]
        reports = aggregate_consensus(
            signals, window_ms=3600_000, min_sources=2, min_score=0.35, now_ms=now
        )
        assert reports[0].symbol == "BTC/USDT"
        assert reports[0].actionable is True
        assert reports[0].reason == "ok"
        assert reports[0].long_weight == pytest.approx(2.0 * 0.8 + 1.0 * 0.8)
        assert reports[1].side == SignalSide.SHORT
        # actionable first, then |score| desc
        assert [r.actionable for r in reports] == [True, True]
