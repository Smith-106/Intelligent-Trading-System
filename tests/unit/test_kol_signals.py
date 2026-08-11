"""Tests for KOL Discord signal aggregation (no live Discord)."""

from __future__ import annotations

import json
from pathlib import Path

from quantflow.strategy.kol_signals.aggregator import aggregate_consensus
from quantflow.strategy.kol_signals.chart_ocr import is_chart_likely, process_attachment
from quantflow.strategy.kol_signals.discord_ingest import (
    ingest_export_file,
    message_to_signal,
)
from quantflow.strategy.kol_signals.models import KolSignal, SignalSide
from quantflow.strategy.kol_signals.parser import parse_trade_text
from quantflow.strategy.kol_signals.registry import load_kol_registry, source_by_channel
from quantflow.strategy.kol_signals.store import KolSignalStore


def test_parse_long_btc_english() -> None:
    p = parse_trade_text("LONG BTCUSDT entry 64000 SL 62000 TP 66000 TP2 68000 4h")
    assert p["side"] == SignalSide.LONG
    assert p["symbol"] == "BTC/USDT"
    assert p["entry"] == 64000.0
    assert p["stop_loss"] == 62000.0
    assert 66000.0 in p["take_profit"]
    assert p["timeframe"] == "4h"
    assert p["confidence"] >= 0.5


def test_parse_cn_short() -> None:
    p = parse_trade_text("开空 以太坊 止损 3500 止盈 3200")
    assert p["side"] == SignalSide.SHORT
    assert p["symbol"] == "ETH/USDT"
    assert p["confidence"] > 0.3


def test_parse_empty() -> None:
    p = parse_trade_text("")
    assert p["side"] == SignalSide.UNKNOWN
    assert p["confidence"] == 0.0


def test_chart_heuristic() -> None:
    assert is_chart_likely(filename="tradingview_btc.png", content_type="image/png")
    assert is_chart_likely(url="https://cdn.discordapp.com/attachments/1/2/x.png")
    assert not is_chart_likely(filename="readme.txt", content_type="text/plain")


def test_process_attachment_no_download() -> None:
    meta = process_attachment(
        url="",
        local_path="",
        filename="chart.png",
        content_type="image/png",
        ocr_backend="none",
        download=False,
    )
    assert meta.is_chart_likely is True
    assert meta.ocr_backend == "none"


def test_message_to_signal_and_consensus() -> None:
    msg = {
        "id": "1001",
        "channel_id": "ch1",
        "content": "Buy $ETH entry: 3000 SL: 2900 TP: 3200",
        "author": {"username": "alpha"},
        "timestamp_ms": 1_700_000_000_000,
        "attachments": [],
    }
    s1 = message_to_signal(msg, source_id="kol_a", weight=1.0, process_images=False)
    assert s1.side == SignalSide.LONG
    assert s1.symbol == "ETH/USDT"

    s2 = KolSignal(
        signal_id="x2",
        source_id="kol_b",
        platform="discord",
        channel_id="ch2",
        message_id="1002",
        author="b",
        created_at_ms=1_700_000_100_000,
        raw_text="long ETHUSDT",
        side=SignalSide.LONG,
        symbol="ETH/USDT",
        confidence=0.7,
        weight=1.2,
    )
    reports = aggregate_consensus(
        [s1, s2],
        window_ms=24 * 3600 * 1000,
        min_sources=2,
        min_score=0.2,
        min_confidence=0.2,
        now_ms=1_700_000_200_000,
    )
    assert reports
    eth = next(r for r in reports if r.symbol == "ETH/USDT")
    assert eth.side == SignalSide.LONG
    assert eth.actionable is True
    assert eth.n_sources >= 2


def test_store_roundtrip(tmp_path: Path) -> None:
    store = KolSignalStore(tmp_path)
    s = KolSignal(
        signal_id="abc",
        source_id="s",
        platform="discord",
        channel_id="c",
        message_id="m1",
        author="a",
        created_at_ms=1,
        raw_text="long BTC",
        side=SignalSide.LONG,
        symbol="BTC/USDT",
        confidence=0.8,
    )
    store.append_signal(s)
    loaded = store.load_signals()
    assert len(loaded) == 1
    assert loaded[0].symbol == "BTC/USDT"
    assert "discord:c:m1" in store.known_message_ids()


def test_ingest_export_file(tmp_path: Path) -> None:
    export = {
        "channel": {"id": "999"},
        "messages": [
            {
                "id": "1",
                "content": "SHORT SOLUSDT SL 100 TP 90",
                "author": {"username": "x"},
                "timestamp_ms": 1_700_000_000_000,
            },
            {
                "id": "1",  # duplicate
                "content": "SHORT SOLUSDT SL 100 TP 90",
                "author": {"username": "x"},
                "timestamp_ms": 1_700_000_000_000,
            },
        ],
    }
    path = tmp_path / "export.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    store = KolSignalStore(tmp_path / "store")
    r1 = ingest_export_file(path, store=store, process_images=False, ocr_backend="none")
    assert r1["ingested"] == 1
    r2 = ingest_export_file(path, store=store, process_images=False, ocr_backend="none")
    assert r2["ingested"] == 0
    assert r2["skipped"] >= 1


def test_registry_load() -> None:
    sources = load_kol_registry("quantflow/config/kol_registry.yaml")
    assert isinstance(sources, list)
    # template sources may be disabled
    assert source_by_channel(sources, "nope") is None
