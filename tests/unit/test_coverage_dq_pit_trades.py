"""Coverage closure: dq_monitor.py + pit_audit.py + trades_ingest.py."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from quantflow.data.dq_monitor import (
    DataQualityMonitor,
    DataQualityScore,
    InMemoryStateStore,
    ValidationResult,
)
from quantflow.data.pit_audit import (
    PITAuditError,
    audit_compute_features_pit,
    audit_frame_no_future,
    max_timestamp_ms,
    run_pit_audit_suite,
)
from quantflow.data.trades_ingest import (
    TradesIngestLoop,
    attach_watch_trades,
    make_fetcher_adapter,
)
from quantflow.data.trades_store import TradesStore

# ===========================================================================
# dq_monitor.py
# ===========================================================================


class _Bar:
    def __init__(self, symbol: str, timestamp: int, close: float, volume: float) -> None:
        self.symbol = symbol
        self.timestamp = timestamp
        self.close = close
        self.volume = volume


def test_dq_dataclass_helpers() -> None:
    res = ValidationResult(valid=True)
    d = res.to_dict()
    assert d["valid"] is True
    assert d["score"]["overall"] == 1.0
    assert "validated_at" in d
    assert (
        ValidationResult(valid=False, score=DataQualityScore(0.5, 0.5, 0.5)).score.overall_score
        == 0.5
    )
    assert not ValidationResult(
        valid=True, score=DataQualityScore(0.4, 0.4, 0.4)
    ).score.is_acceptable
    store = InMemoryStateStore()
    assert store.key_count == 0
    store.clear()  # 123
    assert store.key_count == 0


@pytest.mark.asyncio
async def test_dq_monitor_prometheus_violation_paths() -> None:
    """Single prometheus-enabled monitor: all bar violation + meta counter paths.

    prometheus_client's default registry rejects duplicate metric names, so
    exactly ONE monitor with enable_prometheus=True may be constructed per
    test process — keep all of it in this one test.
    """
    mon = DataQualityMonitor(enable_prometheus=True)  # in-memory fallback
    T0 = 1_700_000_000_000

    # NOTE: MAX_STALENESS_SECONDS is 60.0 (seconds) but bar timestamps are
    # epoch-MILLISECONDS, so any gap > 60ms counts as stale (existing
    # behavior). Use 30ms steps for the mid-range and large gaps for stale.

    # First bar: fresh / continuous / normal -> valid.
    r1 = await mon.validate_bar(_Bar("BTC/USDT", T0, 100.0, 10.0))
    assert r1.valid

    # Staleness > 60ms -> freshness 0.0 (line 392), gauge set (384), violation + counter.
    r2 = await mon.validate_bar(_Bar("BTC/USDT", T0 + 120_000, 100.0, 10.0))
    assert not r2.valid
    assert any(v["type"] == "staleness_exceeded" for v in r2.violations)

    # Staleness <= 0 -> freshness 1.0 (line 388).
    r3 = await mon.validate_bar(_Bar("BTC/USDT", T0 + 120_000, 100.0, 10.0))
    assert r3.valid

    # Price spike in the mid range (0.05, 0.10] -> continuity 0.4 (line 437).
    # Staleness 30ms -> freshness 0.5 -> not a staleness violation.
    r4 = await mon.validate_bar(_Bar("BTC/USDT", T0 + 120_030, 108.0, 10.0))
    assert any(v["type"] == "price_spike_anomaly" for v in r4.violations)

    # Volume ratio in (10, 20] -> anomaly 0.5 (lines 484-487), no volume violation.
    # (overall score 0.65 < 0.7 -> result invalid but no violations appended.)
    r5 = await mon.validate_bar(_Bar("BTC/USDT", T0 + 120_060, 108.0, 150.0))
    assert not any(v["type"] == "volume_anomaly" for v in r5.violations)

    # Volume ratio > 20 -> anomaly 0.0 (lines 488-489), violation + counter.
    r6 = await mon.validate_bar(_Bar("BTC/USDT", T0 + 120_090, 108.0, 500.0))
    assert any(v["type"] == "volume_anomaly" for v in r6.violations)

    # last_close == 0 -> continuity 0.0 (line 426).
    await mon._state_set("dq:last_close:BTC/USDT", 0)
    r7 = await mon.validate_bar(_Bar("BTC/USDT", T0 + 120_120, 100.0, 10.0))
    assert any(v["type"] == "price_spike_anomaly" for v in r7.violations)
    # The zero-close branch returns before storing; reset for the next bars.
    await mon._state_set("dq:last_close:BTC/USDT", 100)

    # avg_volume == 0 with zero volume -> anomaly 1.0 (line 471, ternary True).
    await mon._state_set("dq:avg_volume:BTC/USDT", 0)
    r8 = await mon.validate_bar(_Bar("BTC/USDT", T0 + 120_150, 100.0, 0.0))
    assert r8.valid

    # avg_volume == 0 with non-zero volume -> anomaly 0.0 (line 471, ternary False).
    r9 = await mon.validate_bar(_Bar("BTC/USDT", T0 + 120_180, 100.0, 5.0))
    assert any(v["type"] == "volume_anomaly" for v in r9.violations)

    # Meta-feed violation with prometheus enabled -> counter in _finish_meta_validation (601).
    import time

    stale = mon.validate_funding_rate(
        {
            "symbol": "BTC/USDT",
            "fetched_at_ms": time.time() * 1000.0 - 100 * 3600 * 1000,
            "settled_interval_ms": 8 * 3600 * 1000,
        }
    )
    assert not stale.valid  # 540-543 age-stale path


@pytest.mark.asyncio
async def test_dq_monitor_redis_set_failure_degrades() -> None:
    class _SetBrokenRedis:
        async def get(self, key: str) -> None:
            return None

        async def set(self, key: str, value: Any) -> None:
            raise ConnectionError("redis SET down")

    mon = DataQualityMonitor(redis_cache=_SetBrokenRedis(), enable_prometheus=False)
    assert not mon.is_degraded
    res = await mon.validate_bar(_Bar("BTC/USDT", 1_000, 100.0, 10.0))
    assert res.valid  # first bar path via fallback after SET failure (333-334)
    assert mon.is_degraded
    # Second degradation call -> already-degraded guard (345->exit).
    mon._enter_degraded_mode("again")
    assert mon.is_degraded


@pytest.mark.asyncio
async def test_dq_monitor_check_exception_paths() -> None:
    mon = DataQualityMonitor(enable_prometheus=False)
    await mon._state_set("dq:last_bar:S", "garbage")
    assert await mon._check_freshness(_Bar("S", 1_000, 10.0, 1.0)) == 0.5  # 399-401
    await mon._state_set("dq:last_close:S", "garbage")
    assert await mon._check_price_continuity(_Bar("S", 1_000, 10.0, 1.0)) == 0.5  # 445-447
    await mon._state_set("dq:avg_volume:S", "garbage")
    assert await mon._check_volume_anomaly(_Bar("S", 1_000, 10.0, 1.0)) == 0.5  # 493-495


@pytest.mark.asyncio
async def test_dq_monitor_redis_success_and_get_failure_paths() -> None:
    class _OkRedis:
        async def get(self, key: str) -> None:
            return None

        async def set(self, key: str, value: Any) -> None:
            return None

    mon = DataQualityMonitor(redis_cache=_OkRedis(), enable_prometheus=False)
    res = await mon.validate_bar(_Bar("BTC/USDT", 1_000, 100.0, 10.0))
    assert res.valid  # 332 redis set success return

    class _BrokenRedis:
        async def get(self, key: str) -> str:
            raise ConnectionError("get down")

        async def set(self, key: str, value: Any) -> None:
            raise ConnectionError("set down")

    # No in-memory fallback -> GET failure degrades then returns None (316-317, 321).
    mon2 = DataQualityMonitor(
        redis_cache=_BrokenRedis(), enable_prometheus=False, use_in_memory_fallback=False
    )
    res2 = await mon2.validate_bar(_Bar("BTC/USDT", 1_000, 100.0, 10.0))
    assert res2.valid  # 336->exit fallback is None
    assert mon2.is_degraded


@pytest.mark.asyncio
async def test_dq_monitor_violations_without_prometheus() -> None:
    """All three violation blocks with prometheus disabled (238->242 etc.)."""
    mon = DataQualityMonitor(enable_prometheus=False)
    T0 = 1_700_000_000_000
    await mon.validate_bar(_Bar("BTC/USDT", T0, 100.0, 10.0))
    res = await mon.validate_bar(_Bar("BTC/USDT", T0 + 120_000, 130.0, 500.0))
    types = [v["type"] for v in res.violations]
    assert types == ["staleness_exceeded", "price_spike_anomaly", "volume_anomaly"]
    # Fresh OI snapshot -> no violation (583->593, 599->612).
    import time

    fresh = mon.validate_open_interest({"symbol": "X", "fetched_at_ms": time.time() * 1000.0})
    assert fresh.valid
    # Fresh funding snapshot -> age <= max_age (542->552).
    fresh_funding = mon.validate_funding_rate(
        {
            "symbol": "X",
            "fetched_at_ms": time.time() * 1000.0,
            "settled_interval_ms": 8 * 3600 * 1000,
        }
    )
    assert fresh_funding.valid
    report = await mon.get_quality_report("BTC/USDT")
    assert report["symbol"] == "BTC/USDT"  # 626-629 success path


def test_dq_monitor_prometheus_import_error_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "prometheus_client", None)
    mon = DataQualityMonitor(enable_prometheus=True)
    assert not mon._enable_prometheus  # 206-208 ImportError -> disabled


@pytest.mark.asyncio
async def test_dq_monitor_quality_report_error_path() -> None:
    mon = DataQualityMonitor(enable_prometheus=False)

    class _RaisingStore:
        async def get(self, key: str) -> str:
            raise RuntimeError("state store down")

    mon._fallback_store = _RaisingStore()
    report = await mon.get_quality_report("BTC/USDT")
    assert "error" in report and report["degraded_mode"] is False  # 637-639


def test_dq_monitor_meta_invalid_fields_exception_paths() -> None:
    mon = DataQualityMonitor(enable_prometheus=False)
    res = mon.validate_funding_rate(
        {"symbol": "X", "fetched_at_ms": "oops", "settled_interval_ms": "oops"}
    )
    assert not res.valid  # 522-524 -> NaN guard -> violation
    res2 = mon.validate_open_interest({"symbol": "X", "fetched_at_ms": "oops"})
    assert not res2.valid  # 569-570


def test_dq_monitor_sink_failure_is_silent() -> None:
    class _RaisingSink:
        def record_risk_event(self, event_type: str, severity: str) -> None:
            raise RuntimeError("sink exploded")

    mon = DataQualityMonitor(enable_prometheus=False, monitoring_sink=_RaisingSink())
    res = mon.validate_open_interest({"symbol": "X", "fetched_at_ms": 1.0})
    assert not res.valid  # stale_oi -> sink raises -> 604-605 swallowed


# ===========================================================================
# pit_audit.py
# ===========================================================================


class _FakeRawStore:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def query(self, symbol: str, start: int | None = None, end: int | None = None) -> pd.DataFrame:
        return self.frame


class _FakeFeatureStore:
    def __init__(self, features: pd.DataFrame) -> None:
        self.features = features

    def compute_features(
        self,
        symbol: str,
        timestamp: int,
        indicator_names: list[str],
        raw_store: Any = None,
        meta_store: Any = None,
    ) -> pd.DataFrame:
        return self.features


def test_pit_audit_max_timestamp_and_empty_frames() -> None:
    assert max_timestamp_ms(None) is None
    assert max_timestamp_ms(pd.DataFrame()) is None
    assert max_timestamp_ms(pd.DataFrame({"a": [1]})) is None
    # String column -> astype("int64") raises -> datetime fallback (52-53).
    df = pd.DataFrame({"timestamp": ["2024-01-01", "2024-01-02"]})
    assert max_timestamp_ms(df) is not None


def test_audit_frame_empty_and_missing_column() -> None:
    assert audit_frame_no_future(None, cutoff_ms=100).passed
    res = audit_frame_no_future(pd.DataFrame(), cutoff_ms=100)
    assert res.passed and res.details.get("empty") is True  # 70-76
    res2 = audit_frame_no_future(pd.DataFrame({"close": [1.0]}), cutoff_ms=100)
    assert not res2.passed  # 78-79 missing timestamp column
    with pytest.raises(PITAuditError):
        audit_frame_no_future(pd.DataFrame({"close": [1.0]}), cutoff_ms=100).raise_if_failed()


def test_audit_compute_features_raw_future_and_empty_output() -> None:
    future_raw = _FakeRawStore(pd.DataFrame({"timestamp": [2_000]}))
    res = audit_compute_features_pit(
        _FakeFeatureStore(pd.DataFrame()),
        symbol="S",
        cutoff_ms=1_000,
        raw_store=future_raw,
    )
    assert not res.passed  # raw audit failed (124); empty features (141->150, 150->162)
    assert any("raw_ohlcv" in r for r in res.reasons)


def test_audit_compute_features_output_failures() -> None:
    honest_raw = _FakeRawStore(pd.DataFrame({"timestamp": [500]}))
    # Future output rows -> feat_audit fails (138).
    future_feat = _FakeFeatureStore(pd.DataFrame({"timestamp": [2_000], "computed_at": [2_000]}))
    res = audit_compute_features_pit(future_feat, symbol="S", cutoff_ms=1_000, raw_store=honest_raw)
    assert not res.passed
    assert any("features_output" in r for r in res.reasons)
    # computed_at != cutoff (144-147).
    bad_computed = _FakeFeatureStore(pd.DataFrame({"timestamp": [500], "computed_at": [999]}))
    res2 = audit_compute_features_pit(
        bad_computed, symbol="S", cutoff_ms=1_000, raw_store=honest_raw
    )
    assert not res2.passed
    assert "bad_computed_at" in res2.details
    # meta as-of future (157 True) + in-range column (157 False).
    meta_feat = _FakeFeatureStore(
        pd.DataFrame(
            {
                "timestamp": [500],
                "computed_at": [1_000],
                "meta_max_funding_ts": [2_000],
                "meta_max_oi_ts": [500],
            }
        )
    )
    res3 = audit_compute_features_pit(meta_feat, symbol="S", cutoff_ms=1_000, raw_store=honest_raw)
    assert not res3.passed
    assert any("meta_max_funding_ts" in r for r in res3.reasons)
    assert res3.details["meta_max_oi_ts"] == 500

    # All-NaN meta column -> dropna empty -> 154->151 edge, no violation.
    nan_meta = _FakeFeatureStore(
        pd.DataFrame(
            {
                "timestamp": [500],
                "computed_at": [1_000],
                "meta_max_funding_ts": [float("nan")],
                "meta_max_oi_ts": [float("nan")],
            }
        )
    )
    res4 = audit_compute_features_pit(nan_meta, symbol="S", cutoff_ms=1_000, raw_store=honest_raw)
    assert res4.passed
    assert "meta_max_funding_ts" not in res4.details


def test_pit_audit_suite_compute_and_load_failures() -> None:
    honest_raw = _FakeRawStore(pd.DataFrame({"timestamp": [500]}))

    leaky_compute = _FakeFeatureStore(pd.DataFrame({"timestamp": [2_000], "computed_at": [2_000]}))
    r1 = run_pit_audit_suite(
        leaky_compute, symbol="S", cutoff_ms=1_000, raw_store=honest_raw, also_load=False
    )
    assert not r1.passed  # 211

    class _LeakyLoadFS:
        def compute_features(
            self,
            symbol: str,
            timestamp: int,
            indicator_names: list[str],
            raw_store: Any = None,
            meta_store: Any = None,
        ) -> pd.DataFrame:
            return pd.DataFrame({"timestamp": [500], "computed_at": [1_000]})

        def load_features(
            self, symbol: str, start: int | None = None, end: int | None = None
        ) -> pd.DataFrame:
            return pd.DataFrame({"timestamp": [2_000]})

    r2 = run_pit_audit_suite(
        _LeakyLoadFS(), symbol="S", cutoff_ms=1_000, raw_store=honest_raw, also_load=True
    )
    assert not r2.passed  # 179-185 audit_load_features_pit + 214-219
    assert "load" in r2.details


def test_pit_audit_suite_pass_with_load() -> None:
    class _CleanFS:
        def compute_features(
            self,
            symbol: str,
            timestamp: int,
            indicator_names: list[str],
            raw_store: Any = None,
            meta_store: Any = None,
        ) -> pd.DataFrame:
            return pd.DataFrame({"timestamp": [500], "computed_at": [1_000]})

        def load_features(
            self, symbol: str, start: int | None = None, end: int | None = None
        ) -> pd.DataFrame:
            return pd.DataFrame({"timestamp": [500]})

    res = run_pit_audit_suite(
        _CleanFS(),
        symbol="S",
        cutoff_ms=1_000,
        raw_store=_FakeRawStore(pd.DataFrame({"timestamp": [500]})),
        also_load=True,
    )
    assert res.passed


# ===========================================================================
# trades_ingest.py
# ===========================================================================


@pytest.mark.asyncio
async def test_trades_ingest_poll_error_paths(tmp_path) -> None:
    store = TradesStore(str(tmp_path / "trades"))

    async def retryable(symbol: str, **kw: Any) -> pd.DataFrame:
        if kw:  # called with limit=... -> TypeError, then plain call succeeds
            raise TypeError("kw unsupported")
        return pd.DataFrame({"timestamp": [5], "price": [6.0], "amount": [7.0], "side": ["sell"]})

    loop1 = TradesIngestLoop(store, fetch_trades=retryable, symbols=["BTC/USDT"])
    assert await loop1.poll_once() == 1  # 82-85 TypeError -> plain success

    async def retryable_fail(symbol: str, **kw: Any) -> pd.DataFrame:
        if kw:
            raise TypeError("kw unsupported")
        raise RuntimeError("plain also fails")

    loop2 = TradesIngestLoop(store, fetch_trades=retryable_fail, symbols=["BTC/USDT"])
    assert await loop2.poll_once() == 0  # 82-89
    assert loop2.last_error == "plain also fails"

    async def generic_fail(symbol: str, limit: int = 100) -> pd.DataFrame:
        raise OSError("network down")

    loop3 = TradesIngestLoop(store, fetch_trades=generic_fail, symbols=["BTC/USDT"])
    assert await loop3.poll_once() == 0  # 90-93
    assert loop3.last_error == "network down"

    async def empties(symbol: str, limit: int = 100) -> pd.DataFrame:
        return pd.DataFrame()

    loop4 = TradesIngestLoop(store, fetch_trades=empties, symbols=["BTC/USDT"])
    assert await loop4.poll_once() == 0  # 95

    loop5 = TradesIngestLoop(store, fetch_trades=retryable, symbols=[])
    assert await loop5.poll_once() == 0  # 77


@pytest.mark.asyncio
async def test_trades_ingest_push_trades(tmp_path) -> None:
    store = TradesStore(str(tmp_path / "trades"))
    seen: list[tuple[str, int]] = []

    async def fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
        return pd.DataFrame()

    loop = TradesIngestLoop(
        store,
        fetch_trades=fetch,
        symbols=["BTC/USDT"],
        on_batch=lambda s, df: seen.append((s, len(df))),
    )
    assert await loop.push_trades("BTC/USDT", pd.DataFrame()) == 0  # 107
    assert await loop.push_trades("BTC/USDT", None) == 0  # 107
    n = await loop.push_trades(
        "BTC/USDT",
        pd.DataFrame({"timestamp": [9], "price": [1.0], "amount": [1.0], "side": ["buy"]}),
    )
    assert n == 1 and loop.batches_written == 1 and seen == [("BTC/USDT", 1)]  # 112


@pytest.mark.asyncio
async def test_trades_ingest_start_stop_lifecycle(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quantflow.data.trades_ingest as ingest_module

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(ingest_module.asyncio, "sleep", no_sleep)

    async def ok_fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
        return pd.DataFrame({"timestamp": [1], "price": [2.0], "amount": [3.0], "side": ["buy"]})

    store = TradesStore(str(tmp_path / "trades"))
    loop = TradesIngestLoop(store, fetch_trades=ok_fetch, symbols=["BTC/USDT"], interval_s=1.0)
    t1 = loop.start()
    t2 = loop.start()  # 58-59 already running -> same task
    assert t1 is t2 and loop.is_running
    await loop.stop()
    assert not loop.is_running

    loop2 = TradesIngestLoop(store, fetch_trades=ok_fetch, symbols=["BTC/USDT"])
    await loop2.stop()  # 66->72 task is None -> skip cancel


@pytest.mark.asyncio
async def test_trades_ingest_loop_cycle_error_and_natural_exit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quantflow.data.trades_ingest as ingest_module

    store = TradesStore(str(tmp_path / "trades"))

    async def ok_fetch(symbol: str, limit: int = 100) -> pd.DataFrame:
        return pd.DataFrame({"timestamp": [1], "price": [2.0], "amount": [3.0], "side": ["buy"]})

    def raising_batch(symbol: str, df: pd.DataFrame) -> None:
        raise RuntimeError("callback boom")

    loop = TradesIngestLoop(
        store, fetch_trades=ok_fetch, symbols=["X"], interval_s=1.0, on_batch=raising_batch
    )

    async def stop_on_sleep(_: float) -> None:
        loop._running = False

    monkeypatch.setattr(ingest_module.asyncio, "sleep", stop_on_sleep)
    task = loop.start()
    await task  # on_batch raises -> cycle except (120-122) -> natural while exit (117->128)
    assert loop.last_error == "callback boom"
    assert not loop.is_running


@pytest.mark.asyncio
async def test_trades_ingest_adapter_and_attach(tmp_path) -> None:
    store = TradesStore(str(tmp_path / "trades"))

    class _Fetcher:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        async def fetch_trades(self, symbol: str, limit: int = 100) -> pd.DataFrame:
            self.calls.append(("fetch", symbol, limit))
            return pd.DataFrame(
                {"timestamp": [1], "price": [2.0], "amount": [3.0], "side": ["buy"]}
            )

        async def watch_trades(
            self, symbol: str, callback: Any, *, poll_fallback_interval_s: float = 5.0
        ) -> None:
            self.calls.append(("watch", symbol))
            await callback(
                pd.DataFrame({"timestamp": [2], "price": [4.0], "amount": [5.0], "side": ["sell"]})
            )

    df = _Fetcher()
    adapter = make_fetcher_adapter(df)
    out = await adapter("BTC/USDT", limit=7)  # 134-137
    assert not out.empty and df.calls == [("fetch", "BTC/USDT", 7)]

    loop = TradesIngestLoop(store, fetch_trades=adapter, symbols=["BTC/USDT"])
    await attach_watch_trades(loop, df, "BTC/USDT")
    assert loop.batches_written == 1  # _on_batch -> push_trades
