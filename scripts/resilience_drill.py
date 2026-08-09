#!/usr/bin/env python3
"""Crash recovery + reconciliation alert closed-loop drill (T021).

Runs offline (no exchange) scenarios that must stay green for paper-first ops:

  A) Checkpoint corrupt JSON → StateStore fail-closed (last_error set)
  B) Checkpoint schema mismatch → refuse restore
  C) Artificial position drift → ReconciliationEngine critical alert via sink
  D) Matching books → no alert

Does **not** enable default.yaml state.checkpoint or live trading.

    python scripts/resilience_drill.py
    python scripts/resilience_drill.py --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _RecordingSink:
    def __init__(self) -> None:
        self.alerts: list[dict[str, Any]] = []

    async def send_alert(
        self,
        message: str,
        level: str = "info",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.alerts.append({"message": message, "level": level, "extra": extra or {}})


class _Pos:
    def __init__(self, symbol: str, amount: float) -> None:
        self.symbol = symbol
        self.amount = amount
        self.entry_price = 50_000.0
        self.side = "long"


class _Portfolio:
    """List-shaped portfolio double (get_positions)."""

    def __init__(self, positions: list[_Pos]) -> None:
        self._positions = positions

    def get_positions(self) -> list[_Pos]:
        return list(self._positions)


class _Gateway:
    def __init__(self, positions: list[_Pos], open_orders: list[Any] | None = None) -> None:
        self._positions = positions
        self._open_orders = open_orders or []

    async def query_positions(self) -> list[_Pos]:
        return list(self._positions)

    async def query_open_orders(self, symbol: str | None = None) -> list[Any]:
        return list(self._open_orders)


async def _scenario_corrupt_checkpoint() -> dict[str, Any]:
    from quantflow.execution.state_store import CHECKPOINT_FILENAME, SessionSnapshot, StateStore

    with tempfile.TemporaryDirectory() as td:
        store = StateStore(td)
        store.save_checkpoint(
            SessionSnapshot(
                saved_at_ms=1,
                mode="paper",
                cash=100_000.0,
                positions=[],
                open_orders=[],
                equity=100_000.0,
            )
        )
        path = Path(td) / CHECKPOINT_FILENAME
        path.write_text("{not-json", encoding="utf-8")
        loaded = store.load_checkpoint()
        ok = loaded is None and store.last_error is not None
        return {
            "id": "A_corrupt_checkpoint",
            "pass": ok,
            "detail": {
                "loaded": loaded is not None,
                "last_error": store.last_error,
            },
        }


async def _scenario_schema_mismatch() -> dict[str, Any]:
    from quantflow.execution.state_store import CHECKPOINT_FILENAME, SessionSnapshot, StateStore

    with tempfile.TemporaryDirectory() as td:
        store = StateStore(td)
        store.save_checkpoint(
            SessionSnapshot(
                saved_at_ms=1,
                mode="paper",
                cash=1.0,
                positions=[],
                open_orders=[],
                equity=1.0,
            )
        )
        path = Path(td) / CHECKPOINT_FILENAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = 999
        path.write_text(json.dumps(data), encoding="utf-8")
        loaded = store.load_checkpoint()
        err = store.last_error or ""
        ok = loaded is None and store.last_error is not None and "schema" in err.lower()
        return {
            "id": "B_schema_mismatch",
            "pass": ok,
            "detail": {"last_error": store.last_error},
        }


async def _scenario_drift_alert() -> dict[str, Any]:
    from quantflow.reconciliation.audit_logger import AuditLogger
    from quantflow.reconciliation.engine import ReconciliationEngine

    sink = _RecordingSink()
    local = _Portfolio([_Pos("BTC/USDT", 1.0)])
    remote = _Gateway([_Pos("BTC/USDT", 1.2)])  # 20% drift
    engine = ReconciliationEngine(
        portfolio_manager=local,
        gateway=remote,  # type: ignore[arg-type]
        audit_logger=AuditLogger(secret_key="test-only-drill", enable_file_logging=False),
        drift_threshold_bps=100.0,
        monitoring_sink=sink,  # type: ignore[arg-type]
    )
    report = await engine.run_daily_reconciliation()
    ok = (
        bool(sink.alerts)
        and sink.alerts[-1]["level"] == "critical"
        and sink.alerts[-1]["extra"].get("category") == "reconciliation_drift"
        and report.discrepancies.total_discrepancies >= 1
    )
    return {
        "id": "C_drift_critical_alert",
        "pass": ok,
        "detail": {
            "alerts": sink.alerts,
            "total_discrepancies": report.discrepancies.total_discrepancies,
        },
    }


async def _scenario_no_alert_when_match() -> dict[str, Any]:
    from quantflow.reconciliation.audit_logger import AuditLogger
    from quantflow.reconciliation.engine import ReconciliationEngine

    sink = _RecordingSink()
    engine = ReconciliationEngine(
        portfolio_manager=_Portfolio([_Pos("BTC/USDT", 1.0)]),
        gateway=_Gateway([_Pos("BTC/USDT", 1.0)]),  # type: ignore[arg-type]
        audit_logger=AuditLogger(secret_key="test-only-drill", enable_file_logging=False),
        drift_threshold_bps=100.0,
        monitoring_sink=sink,  # type: ignore[arg-type]
    )
    report = await engine.run_daily_reconciliation()
    ok = not sink.alerts and report.discrepancies.total_discrepancies == 0
    return {
        "id": "D_match_no_alert",
        "pass": ok,
        "detail": {
            "alerts": sink.alerts,
            "total_discrepancies": report.discrepancies.total_discrepancies,
        },
    }


async def run_drill() -> dict[str, Any]:
    scenarios = [
        await _scenario_corrupt_checkpoint(),
        await _scenario_schema_mismatch(),
        await _scenario_drift_alert(),
        await _scenario_no_alert_when_match(),
    ]
    n_pass = sum(1 for s in scenarios if s["pass"])
    return {
        "kind": "resilience_drill",
        "task": "T021",
        "ran_at": datetime.now(UTC).isoformat(),
        "scenarios": scenarios,
        "summary": {
            "n": len(scenarios),
            "pass": n_pass,
            "fail": len(scenarios) - n_pass,
            "overall": "pass" if n_pass == len(scenarios) else "fail",
        },
        "notes": [
            "Offline only — no exchange credentials required",
            "default.yaml state.enabled stays false unless operator opts in",
            "Drift alert path: run_daily → _emit_drift_alert → MonitoringSink",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--out",
        default="data/paper_replay/resilience/latest_drill.json",
    )
    args = ap.parse_args()
    report = asyncio.run(run_drill())

    out = Path(args.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"[resilience] overall={report['summary']['overall']} → {out}")
        for s in report["scenarios"]:
            flag = "PASS" if s["pass"] else "FAIL"
            print(f"  [{flag}] {s['id']}")
    return 0 if report["summary"]["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
