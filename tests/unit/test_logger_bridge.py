"""Tests for structured logging bridge (DFT-7a3c1e9f).

Guards the spec claim "structlog for structured logging": stdlib
``logging.getLogger`` records must flow through structlog's
``ProcessorFormatter`` pipeline alongside native structlog records.
"""

from __future__ import annotations

import io
import logging
import logging.config

import structlog

from quantflow.monitoring.logger import setup_logging


def _capture_root_records(level: str = "INFO", json_format: bool = True) -> io.StringIO:
    """Re-configure logging with an in-memory handler capturing rendered output."""
    setup_logging(level=level, json_format=json_format)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.getLogger().handlers[0].formatter)
    logging.getLogger().handlers = [handler]
    return stream


def test_stdlib_logger_is_structured() -> None:
    """stdlib logging.getLogger output carries structlog fields (event/level/timestamp)."""
    stream = _capture_root_records(json_format=True)
    log = logging.getLogger("quantflow.strategy.trend_following")
    log.info("order_placed")

    out = stream.getvalue()
    assert '"event": "order_placed"' in out
    assert '"level": "info"' in out
    assert '"timestamp"' in out


def test_native_structlog_shares_pipeline() -> None:
    """Native structlog records render through the same ProcessorFormatter."""
    stream = _capture_root_records(json_format=True)
    slog = structlog.get_logger("native")
    slog.info("risk_check", symbol="ETH/USDT")

    out = stream.getvalue()
    assert '"event": "risk_check"' in out
    assert '"symbol": "ETH/USDT"' in out
    assert '"level": "info"' in out


def test_level_filtering_respected() -> None:
    """DEBUG-level records are dropped when level=WARNING."""
    stream = _capture_root_records(level="WARNING", json_format=True)
    log = logging.getLogger("quantflow.signal.risk_engine")
    log.debug("debug_should_be_dropped")
    log.warning("warn_should_pass")

    out = stream.getvalue()
    assert "debug_should_be_dropped" not in out
    assert "warn_should_pass" in out
