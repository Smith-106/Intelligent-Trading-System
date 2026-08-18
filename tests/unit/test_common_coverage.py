"""Focused branch coverage for quantflow.common primitives.

These tests intentionally stay at the common-layer boundary: pure transforms,
validation, context propagation, and in-memory event dispatch are exercised
without importing vectorbt or performing external I/O.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import quantflow.common.tracing as tracing
from quantflow.common.config import (
    AppConfig,
    _deep_merge,
    _load_env_overrides,
    _parse_env_value,
    _set_nested,
    load_config,
    resolve_config_path,
    resolve_config_path_safe,
    save_config,
)
from quantflow.common.cvd import _side_to_sign, cvd_from_trades, cvd_proxy
from quantflow.common.event_bus import EVENT_BAR, Event, EventBus
from quantflow.common.indicator_protocol import IndicatorComputer, NullIndicatorComputer
from quantflow.common.pause_reasons import PauseReasonSet
from quantflow.common.schema_exposure import SchemaExposure, _split_layout
from quantflow.common.url_safety import UnsafeUrlError, validate_outbound_url
from quantflow.common.validators import (
    POSITION_EPSILON,
    validate_columns,
    validate_quantity,
    validate_symbol,
)

# ---------------------------------------------------------------------------
# tracing


def test_tracing_correlation_lifecycle_and_processor() -> None:
    tracing.clear_correlation_id()
    tracing.TRACE_ID_VAR.set(None)
    tracing.SPAN_ID_VAR.set(None)
    assert tracing.get_correlation_id() is None
    tracing.set_correlation_id("corr-1")
    assert tracing.get_correlation_id() == "corr-1"
    assert tracing.get_or_create_correlation_id() == "corr-1"

    processor = tracing.CorrelationIdProcessor()
    assert processor(None, "info", {}) == {"correlation_id": "corr-1"}
    tracing.TRACE_ID_VAR.set("trace-1")
    tracing.SPAN_ID_VAR.set("span-1")
    event = processor(None, "info", {"message": "hello"})
    assert event == {
        "message": "hello",
        "correlation_id": "corr-1",
        "trace_id": "trace-1",
        "span_id": "span-1",
    }
    tracing.clear_correlation_id()
    tracing.TRACE_ID_VAR.set(None)
    tracing.SPAN_ID_VAR.set(None)
    assert processor(None, "info", {}) == {}


@pytest.mark.asyncio
async def test_traced_success_creates_context_and_preserves_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracing.clear_correlation_id()
    ids = iter(["created-corr", "created-span"])
    monkeypatch.setattr(tracing.uuid, "uuid4", lambda: SimpleNamespace(hex=next(ids)))

    @tracing.traced("unit.operation")
    async def operation(value: int) -> tuple[int, str | None, str | None]:
        return value, tracing.get_correlation_id(), tracing.SPAN_ID_VAR.get()

    result = await operation(4)
    assert result == (4, "created-corr", "created-span")
    assert tracing.get_correlation_id() == "created-corr"
    assert tracing.SPAN_ID_VAR.get() == "created-span"


@pytest.mark.asyncio
async def test_traced_error_logs_and_reraises(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    tracing.clear_correlation_id()
    ids = iter(["corr-error", "span-error"])
    monkeypatch.setattr(tracing.uuid, "uuid4", lambda: SimpleNamespace(hex=next(ids)))

    @tracing.traced("unit.failure")
    async def operation() -> None:
        raise RuntimeError("boom")

    with (
        caplog.at_level("ERROR", logger=tracing.logger.name),
        pytest.raises(RuntimeError, match="boom"),
    ):
        await operation()
    assert "SPAN END: unit.failure (error: boom)" in caplog.text


@pytest.mark.asyncio
async def test_tracing_context_restores_previous_id_on_success_and_error() -> None:
    tracing.set_correlation_id("outer")
    async with tracing.TracingContext("inner", correlation_id="inner-id") as context:
        assert context.correlation_id == "inner-id"
        assert tracing.get_correlation_id() == "inner-id"
    assert tracing.get_correlation_id() == "outer"

    with pytest.raises(ValueError, match="bad"):
        async with tracing.TracingContext("failing", correlation_id="error-id"):
            assert tracing.get_correlation_id() == "error-id"
            raise ValueError("bad")
    assert tracing.get_correlation_id() == "outer"
    tracing.clear_correlation_id()


def test_tracing_context_generates_id_and_otel_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing.uuid, "uuid4", lambda: SimpleNamespace(hex="generated-id"))
    context = tracing.TracingContext("generated")
    assert context.correlation_id == "generated-id"
    assert tracing.OTEL_AVAILABLE is False
    tracing.init_otel_tracer("test-service")
    context._token = None
    tracing.clear_correlation_id()
    assert tracing.create_otel_span("operation") is None


@pytest.mark.asyncio
async def test_tracing_context_without_token_exits() -> None:
    context = tracing.TracingContext("no-token", correlation_id="corr")
    await context.__aexit__(None, None, None)


def test_tracing_optional_otel_branch_with_fake_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTracer:
        def start_as_current_span(self, name: str) -> tuple[str, str]:
            return ("span", name)

    trace_module = ModuleType("opentelemetry.trace")
    trace_module.get_tracer = lambda name: FakeTracer()  # type: ignore[attr-defined]
    trace_module.set_tracer_provider = lambda provider: None  # type: ignore[attr-defined]
    trace_module.Status = object  # type: ignore[attr-defined]
    trace_module.StatusCode = object  # type: ignore[attr-defined]
    otel_module = ModuleType("opentelemetry")
    otel_module.trace = trace_module  # type: ignore[attr-defined]

    class Provider:
        def __init__(self) -> None:
            self.processors: list[object] = []

        def add_span_processor(self, processor: object) -> None:
            self.processors.append(processor)

    sdk_trace = ModuleType("opentelemetry.sdk.trace")
    sdk_trace.TracerProvider = Provider  # type: ignore[attr-defined]
    sdk = ModuleType("opentelemetry.sdk")
    sdk.trace = sdk_trace  # type: ignore[attr-defined]
    export = ModuleType("opentelemetry.sdk.trace.export")
    export.BatchSpanProcessor = lambda exporter: ("processor", exporter)  # type: ignore[attr-defined]
    jaeger = ModuleType("opentelemetry.exporter.jaeger.thrift")
    jaeger.JaegerExporter = lambda **kwargs: ("exporter", kwargs)  # type: ignore[attr-defined]
    exporter = ModuleType("opentelemetry.exporter")
    exporter_jaeger = ModuleType("opentelemetry.exporter.jaeger")
    exporter.jaeger = exporter_jaeger  # type: ignore[attr-defined]
    exporter_jaeger.thrift = jaeger  # type: ignore[attr-defined]
    modules = {
        "opentelemetry": otel_module,
        "opentelemetry.trace": trace_module,
        "opentelemetry.sdk": sdk,
        "opentelemetry.sdk.trace": sdk_trace,
        "opentelemetry.sdk.trace.export": export,
        "opentelemetry.exporter": exporter,
        "opentelemetry.exporter.jaeger": exporter_jaeger,
        "opentelemetry.exporter.jaeger.thrift": jaeger,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    loaded = importlib.reload(tracing)
    assert loaded.OTEL_AVAILABLE is True
    loaded.init_otel_tracer("fake")
    assert loaded.create_otel_span("op") == ("span", "op")
    monkeypatch.setattr(
        Provider, "__init__", lambda self: (_ for _ in ()).throw(RuntimeError("bad"))
    )
    loaded.init_otel_tracer("broken")
    monkeypatch.delitem(sys.modules, "opentelemetry.sdk.trace", raising=False)
    monkeypatch.delitem(sys.modules, "opentelemetry.sdk.trace.export", raising=False)
    monkeypatch.delitem(sys.modules, "opentelemetry.exporter.jaeger.thrift", raising=False)
    loaded.init_otel_tracer("missing-sdk")


# ---------------------------------------------------------------------------
# CVD, pause reasons, protocol, URL safety, validators


def test_cvd_from_trades_handles_empty_and_all_side_spellings() -> None:
    empty = cvd_from_trades(pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=str))
    assert empty.empty and empty.dtype == float
    sides = pd.Series(
        [
            "buy",
            "B",
            "long",
            "+1",
            "bid",
            "sell",
            "S",
            "short",
            "-1",
            "ask",
            "2",
            "-2",
            "0",
            "wat",
            None,
        ]
    )
    amounts = pd.Series(np.ones(len(sides)))
    result = cvd_from_trades(pd.Series(range(len(sides))), amounts, sides)
    assert result.iloc[-1] == 0.0
    assert result.index.equals(sides.index)
    assert _side_to_sign(3) == 1.0
    assert _side_to_sign(-3) == -1.0
    assert _side_to_sign(0) == 0.0
    assert _side_to_sign(object()) == 0.0


def test_cvd_proxy_cumulative_direction_and_first_bar() -> None:
    close = pd.Series([10.0, 12.0, 11.0, 11.0], index=["a", "b", "c", "d"])
    volume = pd.Series([5, 2, 3, 4], index=close.index)
    assert cvd_proxy(close, volume).tolist() == [0.0, 2.0, -1.0, -1.0]


def test_pause_reason_set_manual_replace_and_snapshot() -> None:
    pauses = PauseReasonSet()
    assert not pauses.is_paused and pauses.reasons == frozenset()
    pauses.add(" data_stale ")
    pauses.add("")
    pauses.add(None)  # type: ignore[arg-type]
    assert pauses.reasons == frozenset({"data_stale"})
    pauses.set_manual_stop()
    assert pauses.snapshot() == {
        "paused": True,
        "reasons": ["data_stale", "manual_stop"],
        "manual_stop": True,
    }
    pauses.remove("missing")
    pauses.remove(" data_stale ")
    assert pauses.is_paused
    pauses.set_manual_stop(False)
    assert not pauses.is_paused
    pauses.replace([" one ", "", "two", " one "])
    assert pauses.reasons == frozenset({"one", "two"})
    pauses.clear()
    assert pauses.snapshot() == {"paused": False, "reasons": [], "manual_stop": False}


class _Computer:
    def compute_all(
        self, df: pd.DataFrame, indicator_names: list[str] | None = None
    ) -> pd.DataFrame:
        return df


def test_indicator_protocol_runtime_check_and_null_sentinel() -> None:
    assert isinstance(_Computer(), IndicatorComputer)
    with pytest.raises(ValueError, match="No IndicatorComputer injected"):
        NullIndicatorComputer().compute_all(pd.DataFrame(), ["rsi"])


def test_url_safety_accepts_public_urls_and_rejects_invalid_targets() -> None:
    assert validate_outbound_url("https://8.8.8.8/hook") == "https://8.8.8.8/hook"
    assert validate_outbound_url("http://example.com", require_https=False) == "http://example.com"
    for url, kwargs, message in [
        ("", {}, "empty"),
        ("http://example.com", {}, "https"),
        ("ftp://example.com", {"require_https": False}, r"http\(s\)"),
        ("https:///missing", {}, "no host"),
        ("https://user:pass@example.com", {}, "userinfo"),
        ("https://localhost/hook", {}, "loopback"),
        ("https://api.localhost/hook", {}, "loopback"),
        ("https://127.0.0.1/hook", {}, "non-public"),
        ("https://10.0.0.1/hook", {}, "non-public"),
        ("https://169.254.1.1/hook", {}, "non-public"),
        ("https://224.0.0.1/hook", {}, "non-public"),
        ("https://0.0.0.0/hook", {}, "non-public"),
        ("https://192.0.2.1/hook", {}, "non-public"),
    ]:
        with pytest.raises(UnsafeUrlError, match=message):
            validate_outbound_url(url, **kwargs)
    with pytest.raises(UnsafeUrlError, match="unparseable"):
        validate_outbound_url("https://[invalid")


def test_validators_cover_safe_and_rejected_inputs() -> None:
    assert validate_symbol("BTC/USDT") == "BTC_USDT"
    for symbol in ("", "BTC.USDT", "../secret", "x" * 21):
        with pytest.raises(ValueError, match="Invalid symbol"):
            validate_symbol(symbol)
    assert validate_columns(None) is None
    assert validate_columns(["open", "close", "open"]) == ["open", "close"]
    assert validate_columns(("_x", "a2")) == ["_x", "a2"]
    with pytest.raises(ValueError, match="must not be empty"):
        validate_columns([])
    with pytest.raises(ValueError, match="Invalid column"):
        validate_columns(["ok", "bad-name"])
    assert validate_quantity(1.5) == 1.5
    assert POSITION_EPSILON == 1e-10
    for quantity in (0.0, -1.0, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="Invalid quantity"):
            validate_quantity(quantity)


# ---------------------------------------------------------------------------
# schema exposure


def test_schema_exposure_date_sources_and_safe_serialization() -> None:
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "close": [1.0, np.nan, 3.0],
            "tag": ["a", "b", "c"],
        }
    )
    schema = SchemaExposure.from_dataframe(df, "BTC/USDT", splits=(0.5, 0.25, 0.25))
    assert schema.row_count == 3
    assert schema.date_range == ("2024-01-01T00:00:00", "2024-01-03T00:00:00")
    assert schema.columns[1].non_null_count == 2
    assert schema.columns[1].sample_values[0] == 1.0
    assert pd.isna(schema.columns[1].sample_values[1])
    assert schema.columns[1].sample_values[2] == 3.0
    payload = schema.to_dict()
    assert payload["date_range"] == {"start": schema.date_range[0], "end": schema.date_range[1]}
    assert "sample_values" not in payload["columns"][0]
    assert payload["splits"][-1]["end_frac"] == 1.0

    indexed = pd.DataFrame({"x": [1, 2]}, index=pd.date_range("2024-02-01", periods=2))
    assert SchemaExposure.from_dataframe(indexed, "ETH/USDT").date_range == (
        "2024-02-01T00:00:00",
        "2024-02-02T00:00:00",
    )
    plain = SchemaExposure.from_dataframe(pd.DataFrame({"x": [1]}), "SOL/USDT")
    assert plain.date_range == ("unknown", "unknown")
    assert plain.to_dict()["columns"][0]["dtype"] == "int64"


def test_schema_split_layout_validation_rounding_and_empty() -> None:
    assert _split_layout(0, (0.5, 0.25, 0.25))[0].start_frac == 0.0
    layout = _split_layout(10, (0.33, 0.33, 0.34))
    assert sum(s.n_bars for s in layout) == 10
    assert layout[-1].end_frac == 1.0
    for splits, message in [
        ((0.5, 0.5), "must be"),
        ((0.0, 0.5, 0.5), "positive"),
        ((0.4, 0.4, 0.1), "sum"),
    ]:
        with pytest.raises(ValueError, match=message):
            _split_layout(10, splits)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# config


def test_config_path_safe_rejects_absolute_and_parent_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert resolve_config_path_safe(None).exists()
    assert resolve_config_path_safe("config/default.yaml").exists()
    with pytest.raises(ValueError, match="Absolute"):
        resolve_config_path_safe(Path("C:/secret.yaml"))
    with pytest.raises(ValueError, match="Parent"):
        resolve_config_path_safe("../secret.yaml")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", lambda self, strict=False: Path("C:/outside.yaml"))
        with pytest.raises(ValueError, match="escapes"):
            resolve_config_path_safe("safe.yaml")
    assert resolve_config_path_safe("nested/new.yaml").as_posix().endswith("nested/new.yaml")


def test_config_helpers_cover_single_key_env_and_merge_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _parse_env_value("YES") is True
    assert _parse_env_value("No") is False
    assert _parse_env_value("1e2") == 100.0
    nested: dict[str, Any] = {}
    _set_nested(nested, ["mode"], "paper")
    assert nested == {"mode": "paper"}
    assert _deep_merge({"x": {"a": 1}}, {"x": 2}) == {"x": 2}
    monkeypatch.setenv("QUANTFLOW_MODE", "live")
    monkeypatch.setenv("UNRELATED_SETTING", "ignored")
    assert _load_env_overrides()["mode"] == "live"


def test_config_load_and_save_sanitized_nested_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("data:\n  exchange: binance\n", encoding="utf-8")
    monkeypatch.delenv("QUANTFLOW_DATA__EXCHANGE", raising=False)
    cfg = load_config(path, cli_overrides={"data": {"exchange": "okx"}})
    assert cfg.data.exchange == "okx"
    out = tmp_path / "nested" / "saved.yaml"
    save_config(cfg, out)
    assert "***REDACTED***" not in out.read_text(encoding="utf-8")
    assert AppConfig.model_validate(load_config(out).model_dump())
    assert resolve_config_path(tmp_path / "missing.yaml") == tmp_path / "missing.yaml"


# ---------------------------------------------------------------------------
# event bus


@pytest.mark.asyncio
async def test_event_bus_async_background_and_error_isolation() -> None:
    bus = EventBus()
    seen: list[str] = []
    finished = asyncio.Event()

    async def async_handler(event: Event) -> None:
        seen.append(str(event.data))
        finished.set()

    def broken(event: Event) -> None:
        raise RuntimeError("sync boom")

    bus.subscribe(EVENT_BAR, async_handler)
    bus.subscribe(EVENT_BAR, broken)
    bus.publish(Event(EVENT_BAR, "value"))
    await asyncio.wait_for(finished.wait(), timeout=1)
    assert seen == ["value"]
    assert bus.handler_count(EVENT_BAR) == 2


@pytest.mark.asyncio
async def test_event_bus_unsubscribe_one_duplicate_and_publish_async() -> None:
    bus = EventBus()
    seen: list[str] = []

    async def handler(event: Event) -> None:
        seen.append("async")

    bus.subscribe(EVENT_BAR, handler)
    bus.subscribe(EVENT_BAR, handler)
    bus.unsubscribe(EVENT_BAR, handler)
    assert bus.handler_count(EVENT_BAR) == 1
    await bus.publish_async(Event(EVENT_BAR))
    assert seen == ["async"]
    bus.unsubscribe("missing", handler)
    bus.clear()
    assert bus.handler_count(EVENT_BAR) == 0


def test_event_bus_unsubscribe_scans_past_nonmatching_handler() -> None:
    bus = EventBus()

    def first(event: Event) -> None:
        return None

    def second(event: Event) -> None:
        return None

    bus.subscribe(EVENT_BAR, first)
    bus.subscribe(EVENT_BAR, second)
    bus.unsubscribe(EVENT_BAR, second)
    assert bus.handler_count(EVENT_BAR) == 1
