from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from aiohttp.test_utils import TestClient, TestServer

from quantflow.data.store import DataStore
from quantflow.web.app import create_app
from quantflow.web.history import StationHistoryStore
from quantflow.web.service import (
    DataDownloadRequest,
    DataSourceTagRequest,
    ResearchRequest,
    StationService,
    ValidationRequest,
    _query_symbol_frame,
)


class FakeService:
    def __init__(self) -> None:
        self.data_calls = 0
        self.data_download_calls: list[dict[str, object]] = []
        self.data_seed_calls: list[dict[str, object]] = []
        self.data_tag_calls: list[dict[str, object]] = []
        self.execution_calls: list[dict[str, object]] = []
        self.monitoring_calls: list[dict[str, object]] = []
        self._workbench_state: dict[str, object] | None = None

    def overview(self) -> dict[str, object]:
        return {
            "version": "0.1.3",
            "phase": "3",
            "data": {
                "symbol_count": 1,
                "mode": "market",
                "parquet_dir": "data/parquet",
                "duckdb_path": "data/quantflow.duckdb",
                "source_counts": {"okx": 1},
                "source_context": {
                    "title": "Market data ready",
                    "message": "Workspace is backed by tagged OKX market data.",
                },
                "symbols": [
                    {
                        "symbol": "BTC/USDT",
                        "files": 3,
                        "date_range": [1704067200000, 1717718400000],
                        "data_source": "okx",
                        "source_breakdown": {"okx": 3},
                    }
                ],
            },
            "strategies": {"count": 2},
            "monitoring": {"prometheus_port": 9090, "grafana_port": 3000},
            "risk": {"kill_switch_enabled": True},
            "execution": {"mode": "paper"},
            "config_path": "quantflow/config/default.yaml",
        }

    def strategies(self) -> list[dict[str, object]]:
        return [{"strategy_id": "trend_following", "title": "Trend Following"}]

    def data_snapshot(self) -> dict[str, object]:
        self.data_calls += 1
        return {
            "captured_at": "2026-06-08T08:00:00+00:00",
            "mode": "market",
            "summary": {
                "symbol_count": 2,
                "files_total": 5,
                "earliest_bar_at": "2026-01-01T00:00:00+00:00",
                "latest_bar_at": "2026-06-07T00:00:00+00:00",
                "parquet_root_exists": True,
                "duckdb_exists": True,
                "source_counts": {"okx": 1, "demo": 1},
                "market_symbol_count": 1,
                "demo_symbol_count": 1,
                "unknown_symbol_count": 0,
                "hybrid_symbol_count": 0,
            },
            "storage": {
                "parquet_dir": "data/parquet",
                "duckdb_path": "data/quantflow.duckdb",
                "config_path": "quantflow/config/default.yaml",
                "execution_mode": "paper",
                "source_mix": {"okx": 1, "demo": 1},
            },
            "source_context": {
                "title": "Mixed data sources",
                "message": "Workspace contains a mix of market, demo, or unclassified parquet data.",
            },
            "leaders": {
                "latest_symbol": {
                    "symbol": "BTC/USDT",
                    "files": 3,
                    "range_start": "2026-01-01T00:00:00+00:00",
                    "range_end": "2026-06-07T00:00:00+00:00",
                    "coverage_days": 159,
                    "last_bar_age_days": 1,
                    "data_source": "okx",
                },
                "widest_symbol": {
                    "symbol": "BTC/USDT",
                    "files": 3,
                    "range_start": "2026-01-01T00:00:00+00:00",
                    "range_end": "2026-06-07T00:00:00+00:00",
                    "coverage_days": 159,
                    "last_bar_age_days": 1,
                    "data_source": "okx",
                },
            },
            "highlights": ["已覆盖 2 个交易对。"],
            "symbols": [
                {
                    "symbol": "BTC/USDT",
                    "files": 3,
                    "range_start": "2026-01-01T00:00:00+00:00",
                    "range_end": "2026-06-07T00:00:00+00:00",
                    "coverage_days": 159,
                    "last_bar_age_days": 1,
                    "data_source": "okx",
                    "source_breakdown": {"okx": 3},
                },
                {
                    "symbol": "ETH/USDT",
                    "files": 2,
                    "range_start": "2026-02-01T00:00:00+00:00",
                    "range_end": "2026-05-31T00:00:00+00:00",
                    "coverage_days": 120,
                    "last_bar_age_days": 8,
                    "data_source": "demo",
                    "source_breakdown": {"demo": 2},
                },
            ],
        }

    async def download_data(self, request) -> dict[str, object]:
        payload = request.model_dump()
        self.data_download_calls.append(payload)
        return {
            "symbol": request.symbol,
            "timeframe": request.timeframe,
            "start": request.start,
            "end": request.end,
            "rows_saved": 240,
            "raw_rows": 240,
            "data_source": "okx",
            "parquet_dir": "data/parquet",
            "duckdb_path": "data/quantflow.duckdb",
            "date_range": {
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-06-07T00:00:00+00:00",
            },
            "message": f"Saved 240 bars for {request.symbol}.",
        }

    def seed_demo_data(self, request) -> dict[str, object]:
        payload = request.model_dump()
        self.data_seed_calls.append(payload)
        return {
            "symbol": request.symbol,
            "timeframe": request.timeframe,
            "start": request.start,
            "end": request.end,
            "rows_saved": 720,
            "raw_rows": 720,
            "data_source": "demo",
            "parquet_dir": "data/parquet",
            "duckdb_path": "data/quantflow.duckdb",
            "date_range": {
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-06-07T00:00:00+00:00",
            },
            "message": f"Seeded 720 demo bars for {request.symbol}.",
        }

    def tag_data_source(self, request) -> dict[str, object]:
        payload = request.model_dump()
        self.data_tag_calls.append(payload)
        return {
            "symbol": request.symbol,
            "data_source": request.data_source,
            "files_updated": 2,
            "rows_updated": 720,
            "parquet_dir": "data/parquet",
            "duckdb_path": "data/quantflow.duckdb",
            "source_breakdown": {request.data_source: 2},
            "date_range": {
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-06-07T00:00:00+00:00",
            },
            "message": f"Tagged {request.symbol} parquet data as {request.data_source}.",
        }

    def research(self, request) -> dict[str, object]:
        return {
            "request": request.model_dump(),
            "result": {"strategy_id": request.strategy},
            "chart": {
                "candles": [
                    {
                        "chart_index": 0,
                        "label": "2026-01-01T00:00:00+00:00",
                        "open": 100.0,
                        "high": 110.0,
                        "low": 95.0,
                        "close": 108.0,
                        "volume": 1200.0,
                    }
                ],
                "volume": [1200.0],
                "secondary": {"equity": [10000.0], "drawdown": [0.0]},
                "markers": {"entries": [], "exits": []},
                "meta": {"bars_total": 1, "bars_rendered": 1, "entry_count": 0, "exit_count": 0},
                "timeframe": "4h",
                "visible_default": 1,
                "sampled": False,
            },
        }

    def validate(self, request) -> dict[str, object]:
        return {
            "request": request.model_dump(),
            "method": request.method,
            "data_source": "demo",
            "result": {"decision": "GO", "reason": "Validation gate cleared all checks."},
            "signals": {"entries": 4, "exits": 4, "bars": 180},
            "summary": {
                "method": request.method,
                "method_label": "Validation Gate",
                "decision": "GO",
                "outcome_label": "GO",
                "outcome_tone": "accent",
                "reason": "Validation gate cleared all checks.",
                "entries": 4,
                "exits": 4,
                "bars": 180,
                "primary_metric_label": "CPCV PBO",
                "primary_metric_value": 0.12,
                "primary_metric_format": "number",
                "secondary_metrics": [],
                "highlights": ["Validation gate cleared all checks."],
            },
        }

    def research_history(self, limit: int = 12) -> list[dict[str, object]]:
        return [{"record_id": "research-1", "strategy": "trend_following", "symbol": "BTC/USDT"}]

    def validation_history(self, limit: int = 12) -> list[dict[str, object]]:
        return [
            {
                "record_id": "validation-1",
                "strategy": "trend_following",
                "summary": {
                    "decision": "GO",
                    "outcome_label": "GO",
                    "outcome_tone": "accent",
                    "method": "gate",
                    "method_label": "Validation Gate",
                    "reason": "Validation gate cleared all checks.",
                    "entries": 4,
                    "exits": 4,
                    "bars": 180,
                    "primary_metric_label": "CPCV PBO",
                    "primary_metric_value": 0.12,
                    "primary_metric_format": "number",
                },
            }
        ]

    def workbench_state(self) -> dict[str, object] | None:
        return self._workbench_state

    def save_workbench_state(self, payload: dict[str, object]) -> dict[str, object]:
        self._workbench_state = {**payload, "savedAt": "2026-06-09T06:30:00+00:00"}
        return self._workbench_state

    def monitoring_snapshot(
        self,
        *,
        session_snapshot: dict[str, object] | None = None,
        session_history: list[dict[str, object]] | None = None,
        session_events: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        self.monitoring_calls.append(
            {
                "session_snapshot": session_snapshot or {},
                "session_history": session_history or [],
                "session_events": session_events or [],
            }
        )
        return {
            "captured_at": "2026-06-07T12:05:00+00:00",
            "health": {
                "overall_label": "Attention",
                "overall_tone": "warning",
                "summary": "Operator checks need attention.",
                "signals": ["No active trading session."],
            },
            "metrics": {
                "services_up": 1,
                "services_total": 2,
                "validation_no_go": 1,
                "validation_go": 0,
                "warning_events": 0,
                "error_events": 0,
                "research_runs": 1,
                "validation_runs": 1,
                "session_runs": len(session_history or []),
                "session_events": len(session_events or []),
            },
            "platform": {
                "version": "0.1.3",
                "phase": "3",
                "config_path": "quantflow/config/default.yaml",
                "docker_available": False,
                "data_mode": "demo",
                "symbol_count": 1,
                "execution_mode": "paper",
                "kill_switch_enabled": True,
            },
            "runtime": {
                "active_session": False,
                "session_id": None,
                "open_positions": 0,
                "pending_orders": 0,
                "status_label": "Stopped",
                "status_tone": "muted",
            },
            "services": [
                {
                    "service_id": "prometheus",
                    "label": "Prometheus",
                    "port": 9090,
                    "url": "http://127.0.0.1:9090",
                    "reachable": True,
                    "status_label": "Reachable",
                    "tone": "accent",
                    "note": "Metrics scrape endpoint",
                }
            ],
            "activity": {
                "event_levels": {"info": 1},
                "event_types": {"signal": 1},
                "validation_outcomes": {"NO-GO": 1},
            },
            "alerts": [
                {
                    "source": "validation",
                    "title": "Validation Gate",
                    "message": "Validation gate returned a blocking outcome.",
                    "created_at": "2026-06-07T12:05:00+00:00",
                    "tone": "warning",
                }
            ],
            "latest": {
                "research": {"strategy": "trend_following"},
                "validation": {"summary": {"decision": "NO-GO"}},
                "session": {"running": False},
            },
        }

    def execution_snapshot(
        self,
        *,
        session_snapshot: dict[str, object] | None = None,
        session_history: list[dict[str, object]] | None = None,
        session_events: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        self.execution_calls.append(
            {
                "session_snapshot": session_snapshot or {},
                "session_history": session_history or [],
                "session_events": session_events or [],
            }
        )
        return {
            "captured_at": "2026-06-08T08:05:00+00:00",
            "status": {
                "label": "Execution Online",
                "tone": "accent",
                "summary": "执行引擎在线。",
                "session_label": "Running",
                "session_tone": "accent",
            },
            "summary": {
                "mode": "paper",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategy_text": "trend_following",
                "position_count": 1,
                "order_count": 1,
                "gross_notional": 2425.0,
                "pending_notional": 940.0,
                "unrealized_pnl": 25.0,
                "equity": 100900.0,
                "cash": 98500.0,
                "drawdown": -0.012,
                "exposure_pct": 0.0238,
            },
            "control": {
                "session_id": "station-1",
                "running": True,
                "mode": "paper",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "interval_seconds": 30,
                "capital": 100000.0,
                "strategies": ["trend_following"],
                "status_note": "Ready for operator review.",
                "status_tone": "accent",
                "config_text": "paper | BTC/USDT | 1h",
                "strategy_text": "trend_following",
                "uptime_label": "5m 00s",
                "open_positions": 1,
                "pending_orders": 1,
                "recent_event_count": 3,
                "net_exposure_value": 2400.0,
            },
            "telemetry": {
                "point_count": 2,
                "labels": ["2026-06-08T08:00:00+00:00", "2026-06-08T08:05:00+00:00"],
                "equity": [100000.0, 100900.0],
                "cash": [100000.0, 98500.0],
                "market_value": [0.0, 2425.0],
                "drawdown": [0.0, -0.012],
                "open_positions": [0, 1],
                "pending_orders": [0, 1],
                "equity_last": 100900.0,
                "cash_last": 98500.0,
                "market_value_last": 2425.0,
                "drawdown_last": -0.012,
            },
            "risk": {
                "kill_switch_active": False,
                "kill_switch_reason": None,
                "drawdown_ok": True,
                "warning_events": 1,
                "error_events": 0,
            },
            "positions": [
                {
                    "symbol": "BTC/USDT",
                    "quantity": 0.05,
                    "side": "long",
                    "entry_price": 48000.0,
                    "current_price": 48500.0,
                    "market_value": 2425.0,
                    "unrealized_pnl": 25.0,
                    "pnl_pct": 0.0104166667,
                }
            ],
            "orders": [
                {
                    "order_id": "ord-1",
                    "symbol": "BTC/USDT",
                    "side": "buy",
                    "order_type": "limit",
                    "status": "open",
                    "quantity": 0.02,
                    "price": 47000.0,
                }
            ],
            "events": [
                {
                    "event_type": "signal",
                    "title": "Signal generated",
                    "level": "info",
                    "message": "trend_following emitted long signal.",
                    "created_at": "2026-06-07T12:05:00+00:00",
                }
            ],
            "event_mix": {
                "by_type": {"signal": 1, "order": 1},
                "by_level": {"info": 1, "warning": 1},
            },
        }


class FakeSessionManager:
    @staticmethod
    def _snapshot(*, running: bool) -> dict[str, object]:
        return {
            "session_id": "station-1" if running else None,
            "running": running,
            "started_at": "2026-06-07T12:00:00+00:00" if running else None,
            "updated_at": "2026-06-07T12:05:00+00:00" if running else None,
            "request": {
                "mode": "paper",
                "strategies": ["trend_following"],
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "interval_seconds": 30,
                "capital": 100000.0,
            }
            if running
            else None,
            "health": {
                "running": running,
                "drawdown_ok": True,
                "pending_orders": 1 if running else 0,
                "open_positions": 1 if running else 0,
            },
            "portfolio": {
                "cash": 98500.0 if running else 0.0,
                "market_value": 2400.0 if running else 0.0,
                "equity": 100900.0 if running else 0.0,
                "total_value": 100900.0 if running else 0.0,
                "positions": 1 if running else 0,
                "drawdown": -0.012 if running else 0.0,
                "peak_equity": 102500.0 if running else 0.0,
            },
            "positions": [
                {
                    "symbol": "BTC/USDT",
                    "quantity": 0.05,
                    "side": "long",
                    "entry_price": 48000.0,
                    "current_price": 48500.0,
                    "market_value": 2425.0,
                    "unrealized_pnl": 25.0,
                    "pnl_pct": 0.0104166667,
                }
            ]
            if running
            else [],
            "open_orders": [
                {
                    "order_id": "ord-1",
                    "symbol": "BTC/USDT",
                    "side": "buy",
                    "order_type": "limit",
                    "status": "open",
                    "quantity": 0.02,
                    "price": 47000.0,
                    "notional": 940.0,
                    "strategy_id": "trend_following",
                }
            ]
            if running
            else [],
            "kill_switch": {"active": False, "reason": None},
            "last_error": None,
            "recent_events": [
                {
                    "record_id": "event-1",
                    "session_id": "station-1",
                    "event_type": "signal",
                    "title": "Signal generated",
                    "level": "info",
                    "message": "trend_following emitted long signal.",
                    "created_at": "2026-06-07T12:05:00+00:00",
                }
            ]
            if running
            else [],
            "telemetry": {
                "labels": ["2026-06-07T12:00:00+00:00", "2026-06-07T12:05:00+00:00"]
                if running
                else [],
                "equity": [100000.0, 100900.0] if running else [],
                "cash": [100000.0, 98500.0] if running else [],
                "market_value": [0.0, 2400.0] if running else [],
                "drawdown": [0.0, -0.012] if running else [],
                "open_positions": [0, 1] if running else [],
                "pending_orders": [0, 1] if running else [],
            },
            "event_summary": {
                "total": 3 if running else 0,
                "by_type": {"signal": 1, "fill": 1, "risk": 1} if running else {},
                "by_level": {"info": 2, "warning": 1} if running else {},
            },
            "dashboard": {
                "mode": "paper",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategies": ["trend_following"] if running else [],
                "strategy_count": 1 if running else 0,
                "uptime_seconds": 300 if running else 0,
                "uptime_label": "5m 00s" if running else "0s",
                "status_label": "Running" if running else "Stopped",
                "status_tone": "accent" if running else "muted",
                "exposure_pct": 0.0238 if running else 0.0,
                "gross_exposure_pct": 0.0240 if running else 0.0,
                "gross_exposure_value": 2425.0 if running else 0.0,
                "net_exposure_value": 2400.0 if running else 0.0,
                "recent_event_count": 3 if running else 0,
                "warning_event_count": 1 if running else 0,
                "error_event_count": 0,
                "signal_count": 1 if running else 0,
                "fill_count": 1 if running else 0,
                "risk_count": 1 if running else 0,
                "open_positions": 1 if running else 0,
                "pending_orders": 1 if running else 0,
            },
        }

    async def snapshot(self) -> dict[str, object]:
        return self._snapshot(running=False)

    async def start(self, request) -> dict[str, object]:
        snapshot = self._snapshot(running=True)
        snapshot["request"] = request.model_dump()
        return snapshot

    async def stop(self) -> dict[str, object]:
        return self._snapshot(running=False)

    async def trigger_kill_switch(self, reason: str) -> dict[str, object]:
        return {"status": "activated", "reason": reason}

    async def events(self, limit: int = 40, session_id: str | None = None) -> dict[str, object]:
        return {
            "items": [
                {
                    "record_id": "event-1",
                    "session_id": session_id or "station-1",
                    "event_type": "signal",
                    "title": "Signal generated",
                }
            ]
        }

    async def session_history(self, limit: int = 12) -> dict[str, object]:
        return {
            "items": [
                {
                    "session_id": "station-1",
                    "running": False,
                    "started_at": "2026-06-07T12:00:00+00:00",
                    "request": {"mode": "paper", "symbol": "BTC/USDT"},
                    "portfolio": {"equity": 100900.0, "total_value": 100900.0},
                    "health": {"open_positions": 1, "pending_orders": 1},
                    "kill_switch": {"active": False, "reason": None},
                }
            ]
        }

    async def cleanup(self) -> None:
        return None


@pytest.mark.asyncio
async def test_station_root_and_strategy_api() -> None:
    service = FakeService()
    app = create_app(service=service, session_manager=FakeSessionManager())
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            root_response = await client.get("/")
            assert root_response.status == 200
            body = await root_response.text()
            assert "QuantFlow Station" in body
            # React SPA entry point (legacy vanilla UI removed in Phase 5-6 G4):
            # "/" now serves the Vite build output with the #root mount point
            # and /static/dist/ asset references.
            assert 'id="root"' in body
            assert "/static/dist/assets/" in body

            strategies_response = await client.get("/api/strategies")
            assert strategies_response.status == 200
            payload = await strategies_response.json()
            assert payload[0]["strategy_id"] == "trend_following"

            data_response = await client.get("/api/data")
            assert data_response.status == 200
            data_payload = await data_response.json()
            assert data_payload["summary"]["symbol_count"] == 2
            assert data_payload["summary"]["source_counts"]["okx"] == 1
            assert data_payload["leaders"]["latest_symbol"]["symbol"] == "BTC/USDT"
            assert data_payload["leaders"]["latest_symbol"]["data_source"] == "okx"
            assert data_payload["symbols"][1]["data_source"] == "demo"
            assert service.data_calls == 1

            execution_response = await client.get("/api/execution")
            assert execution_response.status == 200
            execution_payload = await execution_response.json()
            assert execution_payload["status"]["label"] == "Execution Online"
            assert execution_payload["summary"]["position_count"] == 1
            assert execution_payload["orders"][0]["order_id"] == "ord-1"
            assert execution_payload["telemetry"]["labels"][0] == "2026-06-08T08:00:00+00:00"
            assert service.execution_calls[0]["session_events"]


@pytest.mark.asyncio
async def test_station_research_and_session_control() -> None:
    service = FakeService()
    app = create_app(service=service, session_manager=FakeSessionManager())
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            download_response = await client.post(
                "/api/data/download",
                json={
                    "symbol": "BTC/USDT",
                    "timeframe": "4h",
                    "start": "2026-01-01",
                    "end": "2026-06-07",
                },
            )
            assert download_response.status == 200
            download_payload = await download_response.json()
            assert download_payload["rows_saved"] == 240
            assert service.data_download_calls[0]["symbol"] == "BTC/USDT"

            seed_response = await client.post(
                "/api/data/seed-demo",
                json={
                    "symbol": "ETH/USDT",
                    "timeframe": "1d",
                    "start": "2026-01-01",
                    "end": "2026-06-07",
                },
            )
            assert seed_response.status == 200
            seed_payload = await seed_response.json()
            assert seed_payload["data_source"] == "demo"
            assert service.data_seed_calls[0]["symbol"] == "ETH/USDT"

            tag_response = await client.post(
                "/api/data/tag-source",
                json={
                    "symbol": "BTC/USDT",
                    "data_source": "okx",
                },
            )
            assert tag_response.status == 200
            tag_payload = await tag_response.json()
            assert tag_payload["data_source"] == "okx"
            assert tag_payload["files_updated"] == 2
            assert service.data_tag_calls[0]["symbol"] == "BTC/USDT"
            assert service.data_tag_calls[0]["data_source"] == "okx"

            research_response = await client.post(
                "/api/research",
                json={"strategy": "trend_following", "symbol": "BTC/USDT"},
            )
            assert research_response.status == 200
            research_payload = await research_response.json()
            assert research_payload["result"]["strategy_id"] == "trend_following"
            assert research_payload["chart"]["candles"][0]["close"] == 108.0

            session_response = await client.post(
                "/api/session/start",
                json={"mode": "paper", "strategies": ["trend_following"], "symbol": "BTC/USDT"},
            )
            assert session_response.status == 200
            session_payload = await session_response.json()
            assert session_payload["running"] is True

            kill_response = await client.post(
                "/api/session/kill-switch",
                json={"reason": "manual_test"},
            )
            assert kill_response.status == 200
            kill_payload = await kill_response.json()
            assert kill_payload["reason"] == "manual_test"


@pytest.mark.asyncio
async def test_station_history_and_event_endpoints() -> None:
    service = FakeService()
    app = create_app(service=service, session_manager=FakeSessionManager())
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            research_history_response = await client.get("/api/research/history")
            assert research_history_response.status == 200
            research_history_payload = await research_history_response.json()
            assert research_history_payload["items"][0]["record_id"] == "research-1"

            validation_history_response = await client.get("/api/validate/history")
            assert validation_history_response.status == 200
            validation_history_payload = await validation_history_response.json()
            assert validation_history_payload["items"][0]["summary"]["decision"] == "GO"
            assert (
                validation_history_payload["items"][0]["summary"]["method_label"]
                == "Validation Gate"
            )

            session_events_response = await client.get("/api/session/events?session_id=station-1")
            assert session_events_response.status == 200
            session_events_payload = await session_events_response.json()
            assert session_events_payload["items"][0]["event_type"] == "signal"

            session_history_response = await client.get("/api/session/history")
            assert session_history_response.status == 200
            session_history_payload = await session_history_response.json()
            assert session_history_payload["items"][0]["session_id"] == "station-1"

            workbench_state_response = await client.get("/api/workbench/state")
            assert workbench_state_response.status == 200
            workbench_state_payload = await workbench_state_response.json()
            assert workbench_state_payload["state"] is None

            saved_workbench_response = await client.post(
                "/api/workbench/state",
                json={
                    "activePanel": "execution",
                    "selectedStrategyId": "trend_following",
                    "terminalDraft": {"mode": "paper", "symbol": "BTC/USDT"},
                },
            )
            assert saved_workbench_response.status == 200
            saved_workbench_payload = await saved_workbench_response.json()
            assert saved_workbench_payload["state"]["activePanel"] == "execution"
            assert saved_workbench_payload["state"]["savedAt"] == "2026-06-09T06:30:00+00:00"

            reloaded_workbench_response = await client.get("/api/workbench/state")
            assert reloaded_workbench_response.status == 200
            reloaded_workbench_payload = await reloaded_workbench_response.json()
            assert reloaded_workbench_payload["state"]["selectedStrategyId"] == "trend_following"

            monitoring_response = await client.get("/api/monitoring")
            assert monitoring_response.status == 200
            monitoring_payload = await monitoring_response.json()
            assert monitoring_payload["health"]["overall_label"] == "Attention"
            assert monitoring_payload["metrics"]["services_up"] == 1
            assert monitoring_payload["services"][0]["service_id"] == "prometheus"
            assert monitoring_payload["alerts"][0]["source"] == "validation"
            assert service.monitoring_calls[0]["session_history"]
            assert service.monitoring_calls[0]["session_events"]


def test_station_service_monitoring_snapshot_aggregates_state(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = StationService(
        history_store=StationHistoryStore(base_dir=tmp_path / "station_history")
    )

    monkeypatch.setattr(
        service,
        "overview",
        lambda: {
            "version": "0.1.3",
            "phase": "3",
            "config_path": "quantflow/config/default.yaml",
            "docker_available": False,
            "monitoring": {
                "prometheus_port": 9090,
                "prometheus_url": "http://127.0.0.1:9090",
                "grafana_port": 3000,
                "grafana_url": "http://127.0.0.1:3000",
            },
            "data": {
                "mode": "demo-seeded",
                "symbol_count": 1,
                "source_counts": {"demo": 1},
                "source_context": {
                    "title": "Demo data seeded",
                    "message": "Workspace currently contains only seeded demo data for front-end walkthroughs.",
                },
            },
            "execution": {"mode": "paper"},
            "risk": {"kill_switch_enabled": True},
        },
    )
    monkeypatch.setattr(
        service,
        "research_history",
        lambda limit=6: [
            {
                "strategy": "trend_following",
                "symbol": "BTC/USDT",
                "created_at": "2026-06-07T12:00:00+00:00",
                "data_source": "okx",
                "summary": {
                    "total_return": 0.12,
                    "sharpe_ratio": 1.4,
                    "max_drawdown": -0.05,
                },
            }
        ],
    )
    monkeypatch.setattr(
        service,
        "validation_history",
        lambda limit=6: [
            {
                "strategy": "trend_following",
                "symbol": "BTC/USDT",
                "created_at": "2026-06-07T12:01:00+00:00",
                "summary": {
                    "decision": "NO-GO",
                    "outcome_label": "NO-GO",
                    "method": "gate",
                    "method_label": "Validation Gate",
                    "reason": "Drawdown exceeded threshold.",
                    "entries": 3,
                    "exits": 3,
                },
            }
        ],
    )
    monkeypatch.setattr(
        "quantflow.web.service._port_reachable",
        lambda host, port, timeout=0.35: port == 9090,
    )
    monkeypatch.setattr(
        "quantflow.web.service.metrics_server_status",
        lambda port: {
            "port": port,
            "attempted": True,
            "started": True,
            "last_error": None,
        },
    )
    monkeypatch.setattr(
        "quantflow.web.service.metrics_registry_snapshot",
        lambda: {
            "available": True,
            "values": {
                "portfolio_value": 101000.0,
                "portfolio_cash": 99800.0,
                "portfolio_drawdown": -0.012,
                "positions_count": 1,
                "orders_total": 4,
                "orders_filled_total": 2,
                "signals_generated_total": 5,
                "risk_events_total": 1,
                "order_latency_count": 2,
                "order_latency_sum": 0.8,
                "bar_latency_count": 4,
                "bar_latency_sum": 0.2,
                "signal_latency_count": 5,
                "signal_latency_sum": 0.5,
            },
        },
    )

    payload = service.monitoring_snapshot(
        session_snapshot={
            "session_id": "station-1",
            "running": True,
            "health": {"open_positions": 1, "pending_orders": 2},
            "dashboard": {"status_label": "Running", "status_tone": "accent"},
            "request": {"mode": "paper", "symbol": "BTC/USDT"},
            "portfolio": {"equity": 101000.0},
            "started_at": "2026-06-07T12:02:00+00:00",
        },
        session_history=[
            {
                "session_id": "station-1",
                "running": False,
                "request": {"mode": "paper", "symbol": "BTC/USDT"},
                "portfolio": {"equity": 101000.0},
                "health": {"open_positions": 1, "pending_orders": 2},
                "started_at": "2026-06-07T12:02:00+00:00",
            }
        ],
        session_events=[
            {
                "event_type": "risk",
                "level": "warning",
                "title": "Risk warning",
                "message": "Exposure nearing threshold.",
                "created_at": "2026-06-07T12:03:00+00:00",
            }
        ],
    )

    assert payload["metrics"]["services_total"] == 2
    assert payload["metrics"]["services_up"] == 1
    assert payload["metrics"]["validation_no_go"] == 1
    assert payload["services"][0]["service_id"] == "prometheus"
    assert payload["services"][0]["status_kind"] == "reachable"
    assert payload["services"][0]["started_in_process"] is True
    assert payload["health"]["overall_tone"] == "warning"
    assert payload["runtime"]["session_id"] == "station-1"
    assert payload["alerts"]
    assert payload["platform"]["source_counts"]["demo"] == 1
    assert payload["platform"]["source_context"]["title"] == "Demo data seeded"
    assert payload["internal_metrics"]["available"] is True
    assert payload["internal_metrics"]["orders_total"] == 4
    assert payload["internal_metrics"]["order_latency_avg"] == pytest.approx(0.4)
    assert payload["internal_metrics"]["bar_latency_avg"] == pytest.approx(0.05)
    assert payload["internal_metrics"]["signal_latency_avg"] == pytest.approx(0.1)
    data_alert = next(alert for alert in payload["alerts"] if alert["source"] == "data")
    assert data_alert["title"] == "Demo data seeded"
    assert "seeded demo data" in data_alert["message"]


def test_station_service_data_snapshot_summarizes_storage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = StationService(
        history_store=StationHistoryStore(base_dir=tmp_path / "station_history")
    )

    monkeypatch.setattr(
        service,
        "overview",
        lambda: {
            "version": "0.1.3",
            "config_path": "quantflow/config/default.yaml",
            "execution": {"mode": "paper"},
            "data": {
                "mode": "market",
                "parquet_dir": str(tmp_path / "parquet"),
                "duckdb_path": str(tmp_path / "quantflow.duckdb"),
                "symbol_count": 2,
                "source_counts": {"okx": 1, "demo": 1},
                "source_context": {
                    "title": "Mixed data sources",
                    "message": "Workspace contains a mix of market, demo, or unclassified parquet data.",
                },
                "symbols": [
                    {
                        "symbol": "BTC/USDT",
                        "files": 3,
                        "date_range": [1704067200000, 1717718400000],
                        "data_source": "okx",
                        "source_breakdown": {"okx": 3},
                    },
                    {
                        "symbol": "ETH/USDT",
                        "files": 2,
                        "date_range": [1706745600000, 1714521600000],
                        "data_source": "demo",
                        "source_breakdown": {"demo": 2},
                    },
                ],
            },
        },
    )

    (tmp_path / "parquet").mkdir(parents=True)
    (tmp_path / "quantflow.duckdb").write_text("", encoding="utf-8")

    payload = service.data_snapshot()

    assert payload["mode"] == "market"
    assert payload["summary"]["symbol_count"] == 2
    assert payload["summary"]["files_total"] == 5
    assert payload["summary"]["parquet_root_exists"] is True
    assert payload["summary"]["duckdb_exists"] is True
    assert payload["summary"]["source_counts"]["okx"] == 1
    assert payload["summary"]["demo_symbol_count"] == 1
    assert payload["leaders"]["latest_symbol"]["symbol"] == "BTC/USDT"
    assert payload["leaders"]["latest_symbol"]["data_source"] == "okx"
    assert payload["leaders"]["widest_symbol"]["files"] == 3
    assert payload["storage"]["source_mix"]["demo"] == 1
    assert payload["symbols"][0]["data_source"] == "okx"
    assert payload["symbols"][1]["source_breakdown"]["demo"] == 2
    assert len(payload["symbols"]) == 2


@pytest.mark.asyncio
async def test_station_service_download_data_persists_market_data(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [1735689600000, 1735704000000],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000.0, 1200.0],
            "symbol": ["BTC/USDT", "BTC/USDT"],
            "timeframe": ["4h", "4h"],
            "datetime": pd.to_datetime(
                ["2025-01-01T00:00:00Z", "2025-01-01T04:00:00Z"],
                utc=True,
            ),
        }
    )

    class FakeFetcher:
        def __init__(self, config) -> None:
            self.config = config

        async def connect(self) -> None:
            return None

        async def fetch_ohlcv(self, symbol, timeframe, start, end):
            assert symbol == "BTC/USDT"
            assert timeframe == "4h"
            assert start == "2025-01-01"
            assert end == "2025-01-02"
            return frame.copy()

        async def disconnect(self) -> None:
            return None

    monkeypatch.setattr(
        "quantflow.web.service.load_config",
        lambda path: SimpleNamespace(
            data=SimpleNamespace(
                exchange="okx",
                parquet_dir=str(tmp_path / "parquet"),
                duckdb_path=str(tmp_path / "quantflow.duckdb"),
            )
        ),
    )
    monkeypatch.setattr("quantflow.data.fetcher.DataFetcher", FakeFetcher)
    monkeypatch.setattr("quantflow.data.cleaner.clean_ohlcv", lambda df: df)

    service = StationService(
        history_store=StationHistoryStore(base_dir=tmp_path / "station_history")
    )
    payload = await service.download_data(
        DataDownloadRequest(
            symbol="BTC/USDT",
            timeframe="4h",
            start="2025-01-01",
            end="2025-01-02",
        )
    )

    assert payload["rows_saved"] == 2
    assert payload["data_source"] == "okx"
    assert payload["date_range"]["start"] == "2025-01-01T00:00:00+00:00"
    assert payload["date_range"]["end"] == "2025-01-01T04:00:00+00:00"
    # P4 suffix isolation: web downloads persist under the -OKX partition.
    assert (tmp_path / "parquet" / "BTC_USDT-OKX" / "2025" / "01.parquet").exists()

    store = DataStore(str(tmp_path / "parquet"), str(tmp_path / "verify.duckdb"))
    try:
        saved = store.query("BTC/USDT-OKX", columns=["timestamp", "close", "data_source"])
    finally:
        store.close()
    assert list(saved["data_source"].unique()) == ["okx"]
    assert saved["close"].tolist() == [101.0, 102.0]


def test_station_service_seed_demo_data_persists_demo_source(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "quantflow.web.service.load_config",
        lambda path: SimpleNamespace(
            data=SimpleNamespace(
                exchange="okx",
                parquet_dir=str(tmp_path / "parquet"),
                duckdb_path=str(tmp_path / "quantflow.duckdb"),
            )
        ),
    )

    service = StationService(
        history_store=StationHistoryStore(base_dir=tmp_path / "station_history")
    )
    payload = service.seed_demo_data(
        DataDownloadRequest(
            symbol="ETH/USDT",
            timeframe="1d",
            start="2025-01-01",
            end="2025-01-10",
        )
    )

    assert payload["data_source"] == "demo"
    assert payload["rows_saved"] == payload["raw_rows"]
    assert payload["rows_saved"] == 720
    assert payload["date_range"]["end"] == "2025-01-10T00:00:00+00:00"
    assert (tmp_path / "parquet" / "ETH_USDT" / "2025" / "01.parquet").exists()

    store = DataStore(str(tmp_path / "parquet"), str(tmp_path / "verify_seed.duckdb"))
    try:
        saved = store.query("ETH/USDT", columns=["timestamp", "data_source"])
    finally:
        store.close()
    assert not saved.empty
    assert len(saved) == 720
    assert list(saved["data_source"].unique()) == ["demo"]


def test_station_service_tag_data_source_persists_market_source(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "quantflow.web.service.load_config",
        lambda path: SimpleNamespace(
            data=SimpleNamespace(
                exchange="okx",
                parquet_dir=str(tmp_path / "parquet"),
                duckdb_path=str(tmp_path / "quantflow.duckdb"),
            )
        ),
    )

    store = DataStore(str(tmp_path / "parquet"), str(tmp_path / "setup.duckdb"))
    frame = pd.DataFrame(
        {
            "timestamp": [1735689600000, 1735704000000],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000.0, 1200.0],
            "symbol": ["BTC/USDT", "BTC/USDT"],
            "timeframe": ["4h", "4h"],
            "datetime": pd.to_datetime(
                ["2025-01-01T00:00:00Z", "2025-01-01T04:00:00Z"],
                utc=True,
            ),
        }
    )
    try:
        store.save(frame, "BTC/USDT")
    finally:
        store.close()

    service = StationService(
        history_store=StationHistoryStore(base_dir=tmp_path / "station_history")
    )
    payload = service.tag_data_source(
        DataSourceTagRequest(
            symbol="BTC/USDT",
            data_source="okx",
        )
    )

    assert payload["data_source"] == "okx"
    assert payload["files_updated"] == 1
    assert payload["rows_updated"] == 2
    assert payload["source_breakdown"]["okx"] == 2

    verify_store = DataStore(str(tmp_path / "parquet"), str(tmp_path / "verify_tag.duckdb"))
    try:
        saved = verify_store.query("BTC/USDT", columns=["timestamp", "data_source"])
    finally:
        verify_store.close()

    assert not saved.empty
    assert list(saved["data_source"].unique()) == ["okx"]


def test_station_service_execution_snapshot_summarizes_runtime() -> None:
    service = StationService()
    service.overview = lambda: {
        "data": {
            "mode": "demo-seeded",
            "source_context": {
                "title": "Demo data seeded",
                "message": "Workspace currently contains only seeded demo data for front-end walkthroughs.",
            },
            "symbols": [
                {
                    "symbol": "BTC/USDT",
                    "data_source": "demo",
                    "source_breakdown": {"demo": 3},
                }
            ],
        },
        "execution": {"mode": "paper"},
    }
    service.research_history = lambda limit=6: [
        {
            "record_id": "research-1",
            "request": {"strategy": "trend_following", "symbol": "BTC/USDT"},
            "data_source": "demo",
        }
    ]
    service.validation_history = lambda limit=6: [
        {
            "record_id": "validation-1",
            "request": {"strategy": "trend_following", "symbol": "BTC/USDT"},
            "data_source": "demo",
            "summary": {
                "method_label": "Validation Gate",
                "outcome_label": "NO-GO",
                "outcome_tone": "danger",
                "reason": "Demo sample is too short for release promotion.",
            },
        }
    ]
    payload = service.execution_snapshot(
        session_snapshot={
            "session_id": "station-1",
            "running": True,
            "request": {
                "mode": "paper",
                "symbol": "BTC/USDT",
                "timeframe": "1h",
                "strategies": ["trend_following"],
            },
            "health": {"drawdown_ok": True},
            "portfolio": {
                "cash": 98500.0,
                "equity": 100900.0,
                "total_value": 100900.0,
                "drawdown": -0.012,
            },
            "positions": [
                {
                    "symbol": "BTC/USDT",
                    "quantity": 0.05,
                    "side": "long",
                    "entry_price": 48000.0,
                    "current_price": 48500.0,
                    "market_value": 2425.0,
                    "unrealized_pnl": 25.0,
                    "pnl_pct": 0.0104166667,
                }
            ],
            "open_orders": [
                {
                    "order_id": "ord-1",
                    "symbol": "BTC/USDT",
                    "side": "buy",
                    "order_type": "limit",
                    "status": "open",
                    "quantity": 0.02,
                    "price": 47000.0,
                    "notional": 940.0,
                }
            ],
            "kill_switch": {"active": False, "reason": None},
            "dashboard": {
                "status_label": "Running",
                "status_tone": "accent",
                "exposure_pct": 0.0238,
            },
            "last_error": None,
            "telemetry": {
                "labels": ["2026-06-07T12:00:00+00:00", "2026-06-07T12:05:00+00:00"],
                "equity": [100000.0, 100900.0],
                "cash": [100000.0, 98500.0],
                "market_value": [0.0, 2425.0],
                "drawdown": [0.0, -0.012],
                "open_positions": [0, 1],
                "pending_orders": [0, 1],
            },
        },
        session_history=[],
        session_events=[
            {
                "event_type": "signal",
                "level": "info",
                "title": "Signal generated",
                "message": "trend_following emitted long signal.",
                "created_at": "2026-06-07T12:05:00+00:00",
            },
            {
                "event_type": "risk",
                "level": "warning",
                "title": "Risk warning",
                "message": "Exposure nearing threshold.",
                "created_at": "2026-06-07T12:06:00+00:00",
            },
        ],
    )

    assert payload["status"]["label"] == "Execution Online"
    assert payload["summary"]["gross_notional"] == 2425.0
    assert payload["summary"]["pending_notional"] == 940.0
    assert payload["summary"]["position_count"] == 1
    assert payload["risk"]["warning_events"] == 1
    assert payload["events"][0]["event_type"] == "signal"
    assert payload["telemetry"]["labels"] == [
        "2026-06-07T12:00:00+00:00",
        "2026-06-07T12:05:00+00:00",
    ]
    assert payload["telemetry"]["equity"] == [100000.0, 100900.0]
    assert payload["telemetry"]["drawdown"] == [0.0, -0.012]
    assert payload["execution_context"]["source_label"] == "最近运行配置"
    assert payload["execution_context"]["data_source"] == "demo"
    assert payload["execution_context"]["data_mode"] == "demo-seeded"
    assert payload["execution_context"]["validation_label"] == "NO-GO"
    assert payload["execution_context"]["validation_method"] == "Validation Gate"


def test_station_load_store_uses_in_memory_duckdb_for_station_reads(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    class FakeStore:
        def __init__(self, parquet_dir: str, duckdb_path: str) -> None:
            captured["parquet_dir"] = parquet_dir
            captured["duckdb_path"] = duckdb_path

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "quantflow.web.service.load_config",
        lambda path: SimpleNamespace(
            data=SimpleNamespace(
                parquet_dir=str(tmp_path / "parquet"),
                duckdb_path=str(tmp_path / "quantflow.duckdb"),
            )
        ),
    )
    monkeypatch.setattr("quantflow.web.service.DataStore", FakeStore)

    from quantflow.web.service import _load_store

    _, store = _load_store("quantflow/config/default.yaml")
    store.close()

    assert captured["parquet_dir"] == str(tmp_path / "parquet")
    assert captured["duckdb_path"] == ":memory:"


def test_station_service_research_returns_chart_payload(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0, 103.0],
            "high": [104.0, 106.0, 107.0, 105.0],
            "low": [99.0, 101.0, 102.0, 100.0],
            "close": [103.0, 105.0, 103.0, 104.0],
            "volume": [1000.0, 1400.0, 1300.0, 1250.0],
            "timeframe": ["4h", "4h", "4h", "4h"],
        },
        index=pd.date_range("2026-01-01", periods=4, freq="4h", tz="UTC"),
    )

    class FakeStore:
        def close(self) -> None:
            return None

    class FakeStrategy:
        def generate_signals(self, _: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
            entries = pd.Series([True, False, False, False], index=frame.index)
            exits = pd.Series([False, False, True, False], index=frame.index)
            return entries, exits

    monkeypatch.setattr(
        "quantflow.web.service.get_strategy_definition",
        lambda strategy_id: SimpleNamespace(
            strategy_id=strategy_id,
            factory=lambda params: FakeStrategy(),
            param_space={},
        ),
    )
    monkeypatch.setattr(
        "quantflow.web.service._load_store",
        lambda config_path: (
            SimpleNamespace(
                data=SimpleNamespace(
                    exchange="okx", parquet_dir="data/parquet", duckdb_path="data/quantflow.duckdb"
                )
            ),
            FakeStore(),
        ),
    )
    monkeypatch.setattr(
        "quantflow.web.service._query_symbol_frame",
        lambda store, symbol, start, end: (frame, "market"),
    )

    service = StationService(
        history_store=StationHistoryStore(base_dir=tmp_path / "station_history")
    )
    payload = service.research(
        ResearchRequest(
            strategy="trend_following",
            symbol="BTC/USDT",
            capital=10000.0,
            fee=0.001,
        )
    )

    assert payload["chart"]["timeframe"] == "4h"
    assert payload["chart"]["candles"][0]["open"] == 100.0
    assert payload["chart"]["candles"][-1]["close"] == 104.0
    assert payload["chart"]["meta"]["bars_total"] == 4
    assert payload["chart"]["markers"]["entries"][0]["execution_index"] == 1
    assert payload["chart"]["markers"]["exits"][0]["execution_index"] == 3
    assert payload["chart"]["secondary"]["equity"][-1] is not None
    assert payload["result"]["start_date"].startswith("2026-01-01 00:00:00+00:00")
    assert payload["result"]["end_date"].startswith("2026-01-01 12:00:00+00:00")


def test_query_symbol_frame_uses_timestamp_column_as_datetime_index() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [1704067200000, 1704081600000, 1704096000000],
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [1200.0, 1300.0, 1400.0],
            "timeframe": ["4h", "4h", "4h"],
            "data_source": ["okx", "okx", "okx"],
        }
    )

    class FakeStore:
        def query(self, symbol: str) -> pd.DataFrame:
            # P4: _query_symbol_frame resolves first, so query receives the
            # storage name (underscores), not the raw trading symbol.
            assert symbol == "BTC_USDT"
            return frame

        def resolve_symbol(self, symbol: str) -> str:
            return "BTC_USDT"

    result_frame, data_source = _query_symbol_frame(FakeStore(), "BTC/USDT")

    assert str(result_frame.index[0]) == "2024-01-01 00:00:00+00:00"
    assert str(result_frame.index[-1]) == "2024-01-01 08:00:00+00:00"
    assert data_source == "okx"


def test_station_service_validate_returns_summary(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0, 103.0],
            "high": [104.0, 106.0, 107.0, 105.0],
            "low": [99.0, 101.0, 102.0, 100.0],
            "close": [103.0, 105.0, 103.0, 104.0],
            "volume": [1000.0, 1400.0, 1300.0, 1250.0],
            "timeframe": ["4h", "4h", "4h", "4h"],
        },
        index=pd.date_range("2026-01-01", periods=4, freq="4h", tz="UTC"),
    )

    class FakeStore:
        def close(self) -> None:
            return None

    class FakeStrategy:
        def generate_signals(self, _: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
            entries = pd.Series([True, False, False, False], index=frame.index)
            exits = pd.Series([False, False, True, False], index=frame.index)
            return entries, exits

    monkeypatch.setattr(
        "quantflow.web.service.get_strategy_definition",
        lambda strategy_id: SimpleNamespace(
            strategy_id=strategy_id,
            factory=lambda params: FakeStrategy(),
            param_space={},
        ),
    )
    monkeypatch.setattr(
        "quantflow.web.service._load_store",
        lambda config_path: (SimpleNamespace(), FakeStore()),
    )
    monkeypatch.setattr(
        "quantflow.web.service._query_symbol_frame",
        lambda store, symbol, start=None, end=None: (frame, "market"),
    )
    monkeypatch.setattr(
        "quantflow.strategy.validation.dsr.deflated_sharpe_ratio",
        lambda sharpe_ratio, n_trials, sample_length: {
            "dsr": 0.61,
            "expected_max_sharpe": 0.42,
            "n_trials": n_trials,
            "observed_sharpe": sharpe_ratio,
            "passed": True,
            "sr_variance": 0.05,
        },
    )

    service = StationService(
        history_store=StationHistoryStore(base_dir=tmp_path / "station_history")
    )
    payload = service.validate(
        ValidationRequest(
            strategy="trend_following",
            symbol="BTC/USDT",
            method="dsr",
            capital=10000.0,
            fee=0.001,
            n_trials=5,
        )
    )

    assert payload["summary"]["method"] == "dsr"
    assert payload["summary"]["method_label"] == "Deflated Sharpe Ratio"
    assert payload["summary"]["outcome_label"] == "PASS"
    assert payload["summary"]["primary_metric_label"] == "DSR"
    assert payload["summary"]["entries"] == 1
    assert payload["history_record"]["summary"]["method_label"] == "Deflated Sharpe Ratio"


def test_station_service_validate_gate_short_sample_returns_no_go(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0],
            "high": [104.0, 106.0, 105.0],
            "low": [99.0, 101.0, 103.0],
            "close": [103.0, 105.0, 104.0],
            "volume": [1000.0, 1400.0, 1300.0],
            "timeframe": ["4h", "4h", "4h"],
        },
        index=pd.date_range("2026-01-01", periods=3, freq="4h", tz="UTC"),
    )

    class FakeStore:
        def close(self) -> None:
            return None

    class FakeStrategy:
        def generate_signals(self, _: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
            entries = pd.Series([True, False, False], index=frame.index)
            exits = pd.Series([False, False, True], index=frame.index)
            return entries, exits

    monkeypatch.setattr(
        "quantflow.web.service.get_strategy_definition",
        lambda strategy_id: SimpleNamespace(
            strategy_id=strategy_id,
            factory=lambda params: FakeStrategy(),
            param_space={},
        ),
    )
    monkeypatch.setattr(
        "quantflow.web.service._load_store",
        lambda config_path: (SimpleNamespace(), FakeStore()),
    )
    monkeypatch.setattr(
        "quantflow.web.service._query_symbol_frame",
        lambda store, symbol, start=None, end=None: (frame, "demo"),
    )

    service = StationService(
        history_store=StationHistoryStore(base_dir=tmp_path / "station_history")
    )
    payload = service.validate(
        ValidationRequest(
            strategy="trend_following",
            symbol="BTC/USDT",
            method="gate",
            capital=10000.0,
            fee=0.001,
            groups=4,
            test_groups=1,
        )
    )

    assert payload["summary"]["method"] == "gate"
    assert payload["summary"]["outcome_label"] == "NO-GO"
    assert payload["summary"]["outcome_tone"] == "danger"
    assert payload["summary"]["reason"] == "CPCV requires at least 4 bars, got 3."
    assert payload["result"]["checks"]["cpcv"]["passed"] is False
    assert payload["result"]["checks"]["cpcv"]["reason"] == "CPCV requires at least 4 bars, got 3."
