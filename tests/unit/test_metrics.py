"""Tests for monitoring metrics helpers."""

from __future__ import annotations

from quantflow.monitoring import metrics


def test_start_metrics_server_handles_exceptions(monkeypatch) -> None:
    def raise_server(port: int) -> None:
        raise RuntimeError("port busy")

    monkeypatch.setattr("quantflow.monitoring.metrics.start_http_server", raise_server)

    metrics.start_metrics_server(9191)


def test_update_portfolio_metrics_sets_gauges() -> None:
    metrics.update_portfolio_metrics(
        total_value=12345.0, cash=2345.0, drawdown=-0.12, n_positions=3
    )

    assert metrics.PORTFOLIO_VALUE._value.get() == 12345.0
    assert metrics.PORTFOLIO_CASH._value.get() == 2345.0
    assert metrics.PORTFOLIO_DRAWDOWN._value.get() == -0.12
    assert metrics.POSITIONS_COUNT._value.get() == 3.0
