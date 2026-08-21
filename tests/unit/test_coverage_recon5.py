"""Coverage completion for quantflow/reconciliation (round 5).

Targets the remaining uncovered lines/branches (baseline):
- audit_logger.py    38%  (mkdir, file logging write, log_report no-to_dict, write failure,
                           verify_entry, query_events full flow)
- ghost_positions.py 86%  (to_dict, _qty/_symbol mapping+None, empty-symbol skip)
- models.py          96%  (PositionSnapshot.from_dict, severity local==0)
- engine.py          97%  (no-interface portfolio, local-zero drift, bg loop exit,
                           loop exception, stop with running task)

No network / no real IO — file IO confined to tmp_path.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest

from quantflow.reconciliation.audit_logger import AuditLogger
from quantflow.reconciliation.engine import ReconciliationEngine
from quantflow.reconciliation.ghost_positions import (
    GhostPositionReport,
    _qty,
    _symbol,
    find_ghost_positions,
)
from quantflow.reconciliation.models import (
    DailyReconReport,
    Discrepancy,
    DiscrepancySet,
    DiscrepancyType,
    PositionSnapshot,
)

# --------------------------------------------------------------------------- #
# audit_logger.py
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_audit_logger_file_logging_roundtrip(tmp_path: Any) -> None:
    """init mkdir (57) + log_event write path (127, 158-163) + verify_entry."""
    audit = AuditLogger(secret_key="sekret", log_dir=tmp_path, enable_file_logging=True)
    entry = await audit.log_event(
        event_type="RECONCILIATION_DRIFT_DETECTED",
        severity="CRITICAL",
        details={"symbol": "BTC/USDT", "drift_bps": 150},
    )
    assert entry["sequence"] == 1
    assert "hmac_signature" in entry
    files = list(tmp_path.glob("audit-*.jsonl"))
    assert len(files) == 1
    assert "RECONCILIATION_DRIFT_DETECTED" in files[0].read_text(encoding="utf-8")
    # verify_entry: valid signature (180-190) + tamper detection
    assert audit.verify_entry(entry) is True
    tampered = dict(entry)
    tampered["details"] = {"symbol": "ETH/USDT"}
    assert audit.verify_entry(tampered) is False


def test_audit_logger_verify_entry_missing_signature() -> None:
    audit = AuditLogger(secret_key="s", enable_file_logging=False)
    assert audit.verify_entry({"sequence": 1}) is False  # 176-177


@pytest.mark.asyncio
async def test_audit_logger_log_report_without_to_dict() -> None:
    audit = AuditLogger(secret_key="s", enable_file_logging=False)

    class _NoDict:
        def __str__(self) -> str:
            return "plain-report"

    entry = await audit.log_report(_NoDict())  # 144 branch
    assert entry["event_type"] == "RECONCILIATION_REPORT"
    assert entry["severity"] == "CRITICAL"  # passed defaults False
    assert entry["details"]["report"] == "plain-report"


@pytest.mark.asyncio
async def test_audit_logger_write_to_file_failure(tmp_path: Any) -> None:
    audit = AuditLogger(secret_key="s", enable_file_logging=False)
    audit._log_dir = tmp_path / "missing" / "sub"  # open() raises → 164-165
    await audit._write_to_file({"sequence": 1})  # must not raise


@pytest.mark.asyncio
async def test_audit_logger_query_events_disabled() -> None:
    audit = AuditLogger(secret_key="s", enable_file_logging=False)
    assert await audit.query_events() == []  # 212-214


@pytest.mark.asyncio
async def test_audit_logger_query_events_full_flow(tmp_path: Any) -> None:
    """Natural inner-loop exhaustion (222->219) requires a file whose last
    line is valid; the corrupt file sorts first under reverse=True."""
    audit = AuditLogger(secret_key="s", log_dir=tmp_path, enable_file_logging=True)
    # corrupt file sorts first under reverse=True → raises → caught (244-245)
    (tmp_path / "audit-2024-01-02.jsonl").write_text("{not-json\n", encoding="utf-8")
    log_file = tmp_path / "audit-2024-01-01.jsonl"
    lines = [
        "\n",  # blank line → skipped (223-224)
        json_entry("E1", "INFO", "2024-01-01T00:00:01"),
        json_entry("E2", "WARNING", "2024-01-01T00:00:02"),
        json_entry("E3", "CRITICAL", "2024-01-01T00:00:03"),
    ]
    log_file.write_text("".join(lines), encoding="utf-8")

    assert len(await audit.query_events()) == 3  # 240

    only_e2 = await audit.query_events(event_type="E2")  # 229-230
    assert len(only_e2) == 1 and only_e2[0]["event_type"] == "E2"

    critical = await audit.query_events(severity="CRITICAL")  # 231-232
    assert len(critical) == 1 and critical[0]["severity"] == "CRITICAL"

    window = await audit.query_events(
        start_time=datetime(2024, 1, 1, 0, 0, 2),  # 235-236
        end_time=datetime(2024, 1, 1, 0, 0, 2, 999999),  # 237-238
    )
    assert len(window) == 1 and window[0]["event_type"] == "E2"

    limited = await audit.query_events(limit=1)  # 242-243
    assert len(limited) == 1


def json_entry(event_type: str, severity: str, ts: str) -> str:
    import json as _json

    return (
        _json.dumps(
            {
                "sequence": 1,
                "timestamp": ts,
                "event_type": event_type,
                "severity": severity,
                "details": {},
            }
        )
        + "\n"
    )


# --------------------------------------------------------------------------- #
# ghost_positions.py
# --------------------------------------------------------------------------- #


def test_ghost_report_to_dict_and_has_ghosts() -> None:
    report = GhostPositionReport(
        ghosts=[{"symbol": "BTC/USDT", "quantity": 1.0, "kind": "untracked"}],
        tracked_with_position=["ETH/USDT"],
        missing_on_exchange=["SOL/USDT"],
        dust_ignored=["DOGE/USDT"],
    )
    assert report.has_ghosts is True
    d = report.to_dict()  # 33
    assert d["has_ghosts"] is True
    assert d["ghosts"][0]["symbol"] == "BTC/USDT"
    empty = GhostPositionReport()
    assert empty.has_ghosts is False


def test_ghost_qty_and_symbol_helpers() -> None:
    assert _qty(None) == 0.0  # 44
    assert _qty({"quantity": 1.5}) == 1.5  # 46
    assert _qty({"size": 2.0}) == 2.0
    assert _symbol({"symbol": "BTC/USDT"}) == "BTC/USDT"  # 52
    assert _symbol({"instrument": "ETH/USDT"}) == "ETH/USDT"


class _PosLike:
    quantity = 3.0
    symbol = "SOL/USDT"


def test_find_ghost_positions_skips_symbol_less_positions() -> None:
    report = find_ghost_positions(
        tracked_symbols=["BTC/USDT"],
        exchange_positions=[
            {"quantity": 1.0},  # no symbol → 80 continue
            None,  # _qty(None) path
            _PosLike(),  # object path
            {"symbol": "BTC/USDT", "quantity": 0.000001},  # dust → ignored
        ],
        dust=0.01,
    )
    assert "BTC/USDT" not in report.ghosts
    assert report.dust_ignored == ["BTC/USDT"]


# --------------------------------------------------------------------------- #
# models.py
# --------------------------------------------------------------------------- #


def test_position_snapshot_from_dict() -> None:
    snap = PositionSnapshot.from_dict(
        {
            "positions": {"BTC/USDT": "x"},
            "timestamp": "2024-01-01T00:00:00",
            "source": "local",
        }
    )  # 48
    assert snap.source == "local"
    assert snap.positions == {"BTC/USDT": "x"}
    default = PositionSnapshot.from_dict({"timestamp": "2024-01-01T00:00:00"})
    assert default.positions == {}
    assert default.source == "unknown"


def test_discrepancy_severity_local_zero() -> None:
    assert (
        Discrepancy(
            type=DiscrepancyType.POSITION_MISMATCH, symbol="X", local_value=0.0, exchange_value=5.0
        ).severity_score
        == 1.0
    )
    assert (
        Discrepancy(
            type=DiscrepancyType.POSITION_MISMATCH, symbol="X", local_value=0.0, exchange_value=0.0
        ).severity_score
        == 0.0
    )  # 76


def test_daily_recon_report_summary() -> None:
    report = DailyReconReport(
        local_snapshot=PositionSnapshot(source="local"),
        exchange_snapshot=PositionSnapshot(source="exchange"),
        discrepancies=DiscrepancySet(items=[]),
    )
    assert "✅" in report.summary()
    assert report.passed is True


# --------------------------------------------------------------------------- #
# engine.py
# --------------------------------------------------------------------------- #


class _EmptyPortfolio:
    """No get_positions / positions / get_symbols interface at all."""


class _ReconGateway:
    async def query_positions(self) -> list[Any]:
        return []

    async def query_open_orders(self, symbol: str) -> list[Any]:
        return []


def _engine(portfolio: Any = None) -> ReconciliationEngine:
    return ReconciliationEngine(
        portfolio_manager=portfolio if portfolio is not None else _EmptyPortfolio(),
        gateway=_ReconGateway(),
    )


@pytest.mark.asyncio
async def test_recon_local_positions_no_interface() -> None:
    """Portfolio without get_positions or positions → empty local snapshot (207->210)."""
    eng = _engine()
    report = await eng.run_daily_reconciliation()
    assert report.status == "completed"
    assert report.local_snapshot.positions == {}
    assert report.discrepancies.total_discrepancies == 0


@pytest.mark.asyncio
async def test_recon_compare_local_zero_amount_skips_mismatch() -> None:
    eng = _engine()
    local = PositionSnapshot(
        positions={"X/USDT": {"amount": 0.0, "entry_price": 0.0, "unrealized_pnl": 0.0}},
        source="local",
    )
    exchange = PositionSnapshot(
        positions={"X/USDT": {"amount": 5.0, "entry_price": 0.0, "unrealized_pnl": 0.0}},
        source="exchange",
    )
    result = await eng._compare_snapshots(local, exchange)  # 281->271 (local_amount == 0)
    assert result.total_discrepancies == 0


@pytest.mark.asyncio
async def test_recon_background_loop_exits_naturally() -> None:
    eng = _engine()
    await eng.start_background_loop(interval_minutes=0.0001)
    await asyncio.sleep(0.05)
    eng._running = False
    assert eng._background_task is not None
    await eng._background_task  # while-condition exit → 468->exit
    assert eng._background_task.done()


@pytest.mark.asyncio
async def test_recon_background_loop_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eng = _engine()
    calls = 0

    async def _boom() -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("recon exploded")

    monkeypatch.setattr(eng, "run_daily_reconciliation", _boom)
    await eng.start_background_loop(interval_minutes=0.0001)
    await asyncio.sleep(0.05)
    assert calls >= 1  # loop caught the exception → 471-472
    eng._running = False
    assert eng._background_task is not None
    await eng._background_task


@pytest.mark.asyncio
async def test_recon_stop_background_loop_with_running_task() -> None:
    eng = _engine()
    await eng.start_background_loop(interval_minutes=0.0001)
    await asyncio.sleep(0.05)
    await eng.stop_background_loop()  # cancels + awaits → 483->489
    assert eng._background_task is None
    await eng.stop_background_loop()  # idempotent
