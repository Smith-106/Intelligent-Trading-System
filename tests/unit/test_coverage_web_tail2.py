"""Web tail2: remaining history/security/service branch gaps."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from quantflow.web.history import StationHistoryStore
from quantflow.web.security import _is_loopback_host, same_origin_guard
from quantflow.web.service import StationService


# ------------------------------------------------------------------ history
class TestHistoryTail2:
    def test_truncate_line_oserror(self, tmp_path: pytest.TempPathFactory) -> None:
        """L207-208: read_text OSError → return."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        missing = tmp_path / "h" / "missing.jsonl"
        store._rotate(missing)

    def test_truncate_line_blank_lines(self, tmp_path: pytest.TempPathFactory) -> None:
        """L214-215: blank lines skipped."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        path = tmp_path / "h" / "session_events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n\n", encoding="utf-8")
        store._rotate(path)
        assert path.exists()

    def test_read_tail_oserror(self, tmp_path: pytest.TempPathFactory) -> None:
        """L269-270: stat OSError → []."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        missing = tmp_path / "h" / "missing.jsonl"
        assert store._read_tail_lines(missing, max_lines=10) == []

    def test_read_tail_leading_blank(self, tmp_path: pytest.TempPathFactory) -> None:
        """L290-291: leading empty line dropped."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        path = tmp_path / "h" / "session_events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n" + json.dumps({"i": 1}) + "\n", encoding="utf-8", newline="\n")
        tail = store._read_tail_lines(path, max_lines=10)
        non_blank = [line for line in tail if line.strip()]
        assert json.loads(non_blank[-1])["i"] == 1


# ------------------------------------------------------------------ security
class TestSecurityTail2:
    def test_is_loopback_host_invalid_ip(self) -> None:
        """L66-67: ip_address ValueError → False."""
        assert _is_loopback_host("not-an-ip") is False

    def test_same_origin_guard_matching(self) -> None:
        """L125-130: same origin → handler runs."""
        import aiohttp.web as web

        async def run() -> None:
            request = SimpleNamespace(
                method="POST",
                headers={"Origin": "http://localhost:8080", "Host": "localhost:8080"},
                app={},
            )

            async def handler(r: Any) -> web.Response:
                return web.Response(text="ok")

            resp = await same_origin_guard(request, handler)
            assert resp.status == 200

        import asyncio

        asyncio.run(run())


# ------------------------------------------------------------------ service
class TestServiceTail2:
    def test_workbench_state_too_large(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1369-1370: payload exceeds byte cap → ValueError."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        service = StationService(history_store=store)
        with pytest.raises(ValueError, match="exceeds"):
            service.save_workbench_state({"big": "x" * (64 * 1024)})

    def test_finite_sum_none_and_bad(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1821-1826: None / non-float values skipped."""
        store = StationHistoryStore(base_dir=tmp_path / "h")
        service = StationService(history_store=store)
        # positions with market_value None / non-numeric / valid
        result = service.execution_snapshot(
            session_snapshot={
                "session_id": "s1",
                "portfolio": {"total_value": 100.0, "cash": 50.0},
                "positions": [
                    {
                        "symbol": "BTC/USDT",
                        "quantity": 1.0,
                        "entry_price": 100.0,
                        "market_value": None,
                        "unrealized_pnl": "bad",
                    },
                    {
                        "symbol": "ETH/USDT",
                        "quantity": 2.0,
                        "entry_price": 50.0,
                        "market_value": 100.0,
                        "unrealized_pnl": 5.0,
                    },
                ],
                "open_orders": [{"notional": None}, {"notional": "bad"}, {"notional": 10.0}],
                "kill_switch": {"active": False},
                "health": {"running": True},
            },
            session_history=[],
            session_events=[],
        )
        assert isinstance(result, dict)

    def test_query_symbol_frame_no_dt_no_ts(self) -> None:
        """L629-643: frame without datetime/timestamp → demo."""
        from quantflow.web.service import _query_symbol_frame

        fake_store = MagicMock()
        fake_store.query = MagicMock(
            return_value=pd.DataFrame({"close": [1.0, 2.0], "open": [1.0, 2.0]})
        )
        frame, tag = _query_symbol_frame(fake_store, "BTC/USDT")
        assert tag == "unknown"
        assert not frame.empty

    def test_validation_summary_pbo_no_total_paths(self) -> None:
        """L804-806: total_paths falsy → path_share None."""
        from quantflow.web.service import _validation_summary

        summary = _validation_summary(
            {
                "method": "pbo",
                "result": {"passed": True, "overfit_paths": 1, "total_paths": 0},
            }
        )
        assert summary["decision"] == "PASS"

    def test_validation_history_payload_not_dict(self, tmp_path: pytest.TempPathFactory) -> None:
        """L1347-1355: payload not dict → no normalization."""
        import json as _json

        store = StationHistoryStore(base_dir=tmp_path / "h")
        path = tmp_path / "h" / "validation_runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json.dumps({"payload": "not-a-dict"}) + "\n", encoding="utf-8")
        service = StationService(history_store=store)
        items = service.validation_history(limit=5)
        assert isinstance(items, list)

    def test_research_signal_fn(self, tmp_path: pytest.TempPathFactory) -> None:
        """L2218-2219: validate() signal_fn invoked for cpcv."""
        from quantflow.web.service import ValidationRequest

        fake_definition = MagicMock()
        fake_strategy = MagicMock()
        fake_strategy.generate_signals = MagicMock(
            return_value=(
                pd.Series([False, True, False]),
                pd.Series([False, False, True]),
            )
        )
        fake_definition.factory = MagicMock(return_value=fake_strategy)
        fake_store = MagicMock()
        fake_store.query = MagicMock(
            return_value=pd.DataFrame(
                {
                    "datetime": pd.date_range("2024-01-01", periods=3, freq="D"),
                    "close": [1.0, 2.0, 3.0],
                    "open": [1.0, 2.0, 3.0],
                }
            )
        )
        fake_store.close = MagicMock()
        fake_config = MagicMock()
        fake_config.data.exchange = "okx"
        fake_config.data.parquet_dir = "/tmp"
        fake_config.data.duckdb_path = "/tmp/d.duckdb"
        with (
            patch("quantflow.web.service.get_strategy_definition", return_value=fake_definition),
            patch("quantflow.web.service._load_store", return_value=(fake_config, fake_store)),
            patch("quantflow.strategy.validation.cpcv.cpcv_backtest") as mock_cpcv,
        ):
            mock_cpcv.return_value = {
                "n_paths": 2,
                "pbo": 0.1,
                "oos_efficiency": 0.5,
                "oos_sharpe_mean": 0.4,
                "oos_sharpe_std": 0.1,
                "oos_sharpe_min": 0.3,
                "passed": True,
            }
            store = StationHistoryStore(base_dir=tmp_path / "h")
            service = StationService(history_store=store)
            result = service.validate(
                ValidationRequest(
                    strategy="trend_following",
                    symbol="BTC/USDT",
                    method="cpcv",
                    params={},
                )
            )
            assert result["method"] == "cpcv"
            # signal_fn must have been called by cpcv_backtest
            assert mock_cpcv.call_args.kwargs["signal_fn"] is not None
            mock_cpcv.call_args.kwargs["signal_fn"](fake_store.query.return_value)
            assert fake_definition.factory.call_count >= 2


# ------------------------------------------------------------------ overview
class TestOverviewTail2:
    def test_overview_timestamps_empty(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L963-968: timestamps all NaN → no date_range."""

        store = StationHistoryStore(base_dir=tmp_path / "h")
        service = StationService(history_store=store)
        fake_store = MagicMock()
        fake_store.list_symbols = MagicMock(return_value=["BTC_USDT"])
        fake_store.query = MagicMock(
            return_value=pd.DataFrame({"timestamp": [None, None], "data_source": ["okx", "okx"]})
        )
        fake_store.get_date_range = MagicMock(return_value=None)
        fake_store.close = MagicMock()
        with (
            patch("quantflow.web.service._open_station_store", return_value=fake_store),
            patch(
                "quantflow.web.service._resolve_frame_data_source",
                return_value=("okx", {"okx": 1}),
            ),
        ):
            result = service.overview()
            assert result["data"]["symbol_count"] == 1


# ------------------------------------------------------------ data_snapshot
class TestDataSnapshotTail2:
    def _service(self, tmp_path: pytest.TempPathFactory) -> StationService:
        store = StationHistoryStore(base_dir=tmp_path / "h")
        return StationService(history_store=store)

    def test_data_snapshot_breakdown_not_dict(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1049-1062: source_breakdown not dict."""

        service = self._service(tmp_path)
        overview = {
            "data": {
                "mode": "market",
                "symbols": [
                    {
                        "symbol": "BTC/USDT",
                        "data_source": "okx",
                        "source_breakdown": "not-a-dict",
                        "date_range": [1700000000000, 1700003600000],
                        "files": 1,
                    }
                ],
                "source_counts": {"okx": 1},
            }
        }
        monkeypatch.setattr(service, "overview", lambda: overview)
        result = service.data_snapshot()
        assert result["mode"] == "market"

    def test_data_snapshot_no_ranges(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1074-1086: range_start/range_end None."""
        service = self._service(tmp_path)
        overview = {
            "data": {
                "mode": "market",
                "symbols": [
                    {
                        "symbol": "BTC/USDT",
                        "data_source": "okx",
                        "source_breakdown": {"okx": 1},
                        "date_range": None,
                        "files": 1,
                    }
                ],
                "source_counts": {"okx": 1},
            }
        }
        monkeypatch.setattr(service, "overview", lambda: overview)
        result = service.data_snapshot()
        assert result["mode"] == "market"

    def test_data_snapshot_hybrid_mode(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1137-1158: hybrid mode highlight."""
        service = self._service(tmp_path)
        overview = {
            "data": {
                "mode": "hybrid",
                "symbols": [
                    {
                        "symbol": "BTC/USDT",
                        "data_source": "hybrid",
                        "source_breakdown": {"okx": 1, "demo": 1},
                        "date_range": [1700000000000, 1700003600000],
                        "files": 1,
                    }
                ],
                "source_counts": {"okx": 1, "demo": 1},
            }
        }
        monkeypatch.setattr(service, "overview", lambda: overview)
        result = service.data_snapshot()
        assert result["mode"] == "hybrid"

    def test_data_snapshot_unknown_mode(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1155-1160: mode not in any highlight branch → no extra highlight."""
        service = self._service(tmp_path)
        overview = {
            "data": {
                "mode": "custom",
                "symbols": [
                    {
                        "symbol": "BTC/USDT",
                        "data_source": "unknown",
                        "source_breakdown": {},
                        "date_range": [1700000000000, 1700003600000],
                        "files": 1,
                    }
                ],
                "source_counts": {"unknown": 1},
            }
        }
        monkeypatch.setattr(service, "overview", lambda: overview)
        result = service.data_snapshot()
        assert result["mode"] == "custom"


# --------------------------------------------------------- monitoring_snapshot
class TestMonitoringSnapshotTail2:
    def _service(self, tmp_path: pytest.TempPathFactory) -> StationService:
        store = StationHistoryStore(base_dir=tmp_path / "h")
        return StationService(history_store=store)

    def _overview(self, mode: str = "market") -> dict[str, Any]:
        return {
            "version": "1.0",
            "phase": 3,
            "config_path": "/test",
            "docker_available": True,
            "monitoring": {"prometheus_port": 8000, "grafana_port": 3000},
            "data": {
                "parquet_dir": "/tmp/test",
                "duckdb_path": "/tmp/test.duckdb",
                "mode": mode,
                "symbol_count": 1,
                "source_counts": {"okx": 1},
                "symbols": [
                    {
                        "symbol": "BTC/USDT",
                        "data_source": "okx",
                        "files": 1,
                        "date_range": [1700000000000, 1700003600000],
                        "source_breakdown": {"okx": 1},
                    }
                ],
            },
            "risk": {"max_drawdown": -0.1},
        }

    def test_monitoring_empty_decisions(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1530-1535: empty decision + loop exit."""
        service = self._service(tmp_path)
        monkeypatch.setattr(service, "overview", lambda: self._overview())
        monkeypatch.setattr(service, "research_history", lambda limit=6: [])
        monkeypatch.setattr(service, "validation_history", lambda limit=6: [{"summary": {}}])
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
            patch("quantflow.web.service._port_reachable", return_value=True),
        ):
            result = service.monitoring_snapshot(
                session_snapshot={"running": True, "session_id": "s1"},
                session_history=[],
                session_events=[],
            )
            assert result["health"]["overall_tone"] == "accent"

    def test_monitoring_no_go_danger(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1568-1571: NO-GO with health_tone already danger."""
        service = self._service(tmp_path)
        monkeypatch.setattr(service, "overview", lambda: self._overview())
        monkeypatch.setattr(service, "research_history", lambda limit=6: [])
        monkeypatch.setattr(
            service,
            "validation_history",
            lambda limit=6: [{"summary": {"outcome_label": "NO-GO"}}],
        )
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": True, "started": False, "last_error": "boom"},
            ),
            patch("quantflow.web.service._port_reachable", return_value=False),
        ):
            result = service.monitoring_snapshot(
                session_snapshot={"running": True, "session_id": "s1"},
                session_history=[],
                session_events=[],
            )
            assert result["health"]["overall_tone"] == "danger"

    def test_monitoring_no_prometheus(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1573-1595 / L1694-1725: prometheus_service None."""
        service = self._service(tmp_path)
        monkeypatch.setattr(service, "overview", lambda: self._overview())
        monkeypatch.setattr(service, "research_history", lambda limit=6: [])
        monkeypatch.setattr(service, "validation_history", lambda limit=6: [])
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
            patch("quantflow.web.service._port_reachable", return_value=True),
        ):
            result = service.monitoring_snapshot(
                session_snapshot={"running": True, "session_id": "s1"},
                session_history=[],
                session_events=[],
            )
            assert result["health"]["overall_tone"] == "accent"

    def test_monitoring_no_latest_validation(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1646-1669: latest_validation None."""
        service = self._service(tmp_path)
        monkeypatch.setattr(service, "overview", lambda: self._overview())
        monkeypatch.setattr(service, "research_history", lambda limit=6: [])
        monkeypatch.setattr(service, "validation_history", lambda limit=6: [])
        with (
            patch(
                "quantflow.web.service.metrics_registry_snapshot",
                return_value={"values": {}, "available": False},
            ),
            patch(
                "quantflow.web.service.metrics_server_status",
                return_value={"attempted": False, "started": False},
            ),
            patch("quantflow.web.service._port_reachable", return_value=True),
        ):
            result = service.monitoring_snapshot(
                session_snapshot={"running": True, "session_id": "s1"},
                session_history=[],
                session_events=[],
            )
            assert result["health"]["overall_tone"] == "accent"


# --------------------------------------------------------- execution_snapshot
class TestExecutionSnapshotTail2:
    def test_execution_hybrid_and_artifact(
        self, tmp_path: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """L1966-1969 / L1979-1981 / L2028-2035: custom mode + artifact fallbacks."""
        service = StationService(history_store=StationHistoryStore(base_dir=tmp_path / "h"))
        overview = {
            "data": {
                "mode": "custom",
                "symbols": [
                    {
                        "symbol": "BTC/USDT",
                        "data_source": "unknown",
                        "files": 1,
                        "date_range": [1700000000000, 1700003600000],
                        "source_breakdown": {"okx": 1},
                    }
                ],
                "source_counts": {"okx": 1},
            }
        }
        monkeypatch.setattr(service, "overview", lambda: overview)
        monkeypatch.setattr(
            service,
            "research_history",
            lambda limit=6: [{"payload": {"request": "not-dict"}}],
        )
        monkeypatch.setattr(
            service,
            "validation_history",
            lambda limit=6: [{"payload": {"request": "not-dict"}}],
        )
        result = service.execution_snapshot(
            session_snapshot={
                "session_id": "s1",
                "portfolio": {"total_value": 100.0, "cash": 50.0},
                "positions": [],
                "open_orders": [],
                "kill_switch": {"active": False},
                "health": {"running": True},
            },
            session_history=[],
            session_events=[],
        )
        assert result["execution_context"]["source_type"] == "runtime"
