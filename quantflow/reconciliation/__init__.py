"""Reconciliation module — detect and resolve position/order drift.

ISS-20260720-004: This module implements the missing reconciliation infrastructure
that has been acknowledged but never implemented since project inception.

Components:
- ReconciliationEngine: Core engine with background reconciliation loop
- AuditLogger: HMAC-signed audit trail for compliance
- Models: Snapshot/Discrepancy dataclasses

Usage:
    engine = ReconciliationEngine(portfolio_manager, gateway)
    await engine.start_background_loop(interval_minutes=5)
    report = await engine.run_daily_reconciliation()
"""

from quantflow.reconciliation.engine import ReconciliationEngine
from quantflow.reconciliation.audit_logger import AuditLogger
from quantflow.reconciliation.models import (
    PositionSnapshot,
    Discrepancy,
    DiscrepancySet,
    DailyReconReport,
)

__all__ = [
    "ReconciliationEngine",
    "AuditLogger",
    "PositionSnapshot",
    "Discrepancy",
    "DiscrepancySet",
    "DailyReconReport",
]
