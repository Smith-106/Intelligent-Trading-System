"""Core reconciliation engine — detect and resolve position/order drift.

ISS-20260720-004: Implements the missing reconciliation infrastructure.

Features:
- Background reconciliation loop (configurable interval)
- Position snapshot comparison (L4 vs exchange)
- Orphan order detection via query_open_orders()
- Drift detection with configurable thresholds
- Integration with AuditLogger for compliance

Usage:
    engine = ReconciliationEngine(
        portfolio_manager=portfolio,
        gateway=okx_gateway,
        audit_logger=audit,
        drift_threshold_bps=100,  # 1%
    )

    # Run one-off reconciliation
    report = await engine.run_daily_reconciliation()

    # Start background loop
    await engine.start_background_loop(interval_minutes=5)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from quantflow.common.monitoring_sink import MonitoringSink, NullMonitoringSink
from quantflow.common.redaction import redact_secrets
from quantflow.execution.gateway_base import GatewayBase, GatewayError
from quantflow.reconciliation.audit_logger import AuditLogger
from quantflow.reconciliation.models import (
    DailyReconReport,
    Discrepancy,
    DiscrepancySet,
    DiscrepancyType,
    PositionSnapshot,
)

logger = logging.getLogger(__name__)


class ReconciliationEngine:
    """Core reconciliation engine for detecting position/order drift.

    This engine addresses ISS-20260720-004 by implementing:
    1. Position reconciliation (L4 portfolio vs exchange positions)
    2. Order reconciliation (local pending orders vs exchange open orders)
    3. Orphan detection (orders/positions that exist on one side only)
    4. Drift monitoring with configurable thresholds
    5. Audit trail with HMAC signatures

    Thread Safety:
    - All operations are async and use asyncio locks
    - Safe for concurrent access from multiple strategies
    """

    def __init__(
        self,
        portfolio_manager: Any,  # PortfolioManager from L4
        gateway: GatewayBase,
        audit_logger: AuditLogger | None = None,
        drift_threshold_bps: float = 100.0,  # 1% default
        order_staleness_threshold_seconds: float = 300.0,  # 5 minutes
        order_manager: Any | None = None,
        monitoring_sink: MonitoringSink | None = None,
    ) -> None:
        """Initialize reconciliation engine.

        Args:
            portfolio_manager: L4 portfolio manager for local state
            gateway: Exchange gateway for remote state
            audit_logger: Optional audit logger (creates default if None)
            drift_threshold_bps: Position drift threshold in basis points
            order_staleness_threshold_seconds: Age threshold for orphan orders
            order_manager: Optional L5 OrderManager (duck-typed; needs
                ``get_open_orders() -> list[Order]``). When injected, local
                in-flight order ids for orphan detection are derived from it
                instead of the portfolio's pending ledger.
            monitoring_sink: Optional L6 observability seam (arch-013
                MonitoringSink Protocol). Significant drift emits
                ``send_alert(level='critical')``. Default Null = no-op.
        """
        self._portfolio = portfolio_manager
        self._gateway = gateway
        self._order_manager = order_manager
        # L5→L6 seam: depend on the Protocol only, never import monitoring/.
        self._sink: MonitoringSink = monitoring_sink or NullMonitoringSink()
        # SEC-RV19-A1: no hardcoded signing key — without QUANTFLOW_AUDIT_HMAC_KEY
        # the audit trail stays unsigned (with a loud warning) instead of being
        # signed with a public constant anyone could forge. A no-op stub keeps
        # the reconciliation flow alive; it just writes nothing.
        self._audit = audit_logger or self._build_default_audit()
        self._drift_threshold_bps = drift_threshold_bps
        self._order_staleness_threshold = order_staleness_threshold_seconds

        self._lock = asyncio.Lock()
        self._background_task: asyncio.Task[None] | None = None
        self._running = False

    @staticmethod
    def _build_default_audit() -> Any:
        import os

        key = os.environ.get("QUANTFLOW_AUDIT_HMAC_KEY", "")
        if not key:
            logger.warning(
                "QUANTFLOW_AUDIT_HMAC_KEY unset — reconciliation audit trail will be UNSIGNED"
            )

        class _UnsignedAudit:
            """No-op stand-in preserving the AuditLogger call surface."""

            async def log_event(self, *args: Any, **kwargs: Any) -> None:
                return None

            async def log_report(self, report: Any) -> dict[str, Any]:
                return {"signed": False}

            async def close(self) -> None:
                return None

        if not key:
            return _UnsignedAudit()
        return AuditLogger(secret_key=key, enable_file_logging=False)

    async def run_daily_reconciliation(self) -> DailyReconReport:
        """Run complete reconciliation and generate report.

        This is the main entry point for one-off reconciliation runs.

        Returns:
            DailyReconReport with snapshots, discrepancies, and metadata
        """
        start_time = time.time()
        reconciliation_id = f"RECON-{uuid.uuid4().hex[:12]}"

        logger.info("Starting reconciliation %s", reconciliation_id)

        try:
            # Capture snapshots
            local_snapshot = await self._capture_local_snapshot()
            exchange_snapshot = await self._capture_exchange_snapshot()

            # Compare and detect discrepancies
            discrepancies = await self._compare_snapshots(local_snapshot, exchange_snapshot)

            # Any discrepancy already exceeded the configured drift/staleness
            # thresholds, so each reconciliation run with findings emits
            # exactly one critical alert through the MonitoringSink (T-s1-01
            # fail-closed observability; Null sink when none injected).
            if discrepancies.total_discrepancies > 0:
                await self._emit_drift_alert(discrepancies, reconciliation_id)

            # Handle significant drift
            if discrepancies.max_severity > 0.8:  # Critical threshold
                await self._handle_significant_drift(discrepancies, reconciliation_id)

            # Generate report
            duration = time.time() - start_time
            report = DailyReconReport(
                local_snapshot=local_snapshot,
                exchange_snapshot=exchange_snapshot,
                discrepancies=discrepancies,
                reconciled_at=datetime.utcnow(),
                reconciliation_id=reconciliation_id,
                duration_seconds=duration,
                status="completed",
            )

            # Log to audit trail
            await self._audit.log_report(report)

            logger.info("Reconciliation %s completed: %s", reconciliation_id, report.summary())

            return report

        except Exception as e:
            logger.error(
            "Reconciliation %s failed: %s", reconciliation_id, redact_secrets(str(e))
        )

            # Create failure report
            duration = time.time() - start_time
            return DailyReconReport(
                local_snapshot=PositionSnapshot(source="local"),
                exchange_snapshot=PositionSnapshot(source="exchange"),
                discrepancies=DiscrepancySet(),
                reconciled_at=datetime.utcnow(),
                reconciliation_id=reconciliation_id,
                duration_seconds=duration,
                status="failed",
                error_message=str(e),
            )

    @staticmethod
    def _position_entry(pos: Any) -> dict[str, Any]:
        """Normalize a position object into the snapshot entry shape.

        Supports both the L4 ``Position`` model (``quantity``) and the
        gateway/legacy shape (``amount``) without importing either layer.
        """
        amount = getattr(pos, "amount", None)
        if amount is None:
            amount = getattr(pos, "quantity", 0.0)
        return {
            "amount": amount,
            "entry_price": getattr(pos, "entry_price", 0.0),
            "unrealized_pnl": getattr(pos, "unrealized_pnl", 0.0),
        }

    def _local_positions(self) -> dict[str, dict[str, Any]]:
        """Read local positions from the injected portfolio manager.

        Dual-interface duck-typing: prefer ``get_positions()`` (list-shaped
        managers / test doubles), fall back to the ``positions`` mapping
        property (production PortfolioManager). No L4 import — layering is
        preserved by attribute probing only.
        """
        positions: dict[str, dict[str, Any]] = {}
        getter = getattr(self._portfolio, "get_positions", None)
        if callable(getter):
            for pos in getter():
                positions[pos.symbol] = self._position_entry(pos)
            return positions
        mapping = getattr(self._portfolio, "positions", None)
        if mapping is not None:
            for symbol, pos in dict(mapping).items():
                positions[symbol] = self._position_entry(pos)
        return positions

    async def _capture_local_snapshot(self) -> PositionSnapshot:
        """Capture current local portfolio state.

        Returns:
            PositionSnapshot with all local positions
        """
        async with self._lock:
            return PositionSnapshot(
                positions=self._local_positions(),
                timestamp=datetime.utcnow(),
                source="local",
            )

    async def _capture_exchange_snapshot(self) -> PositionSnapshot:
        """Capture current exchange state.

        Returns:
            PositionSnapshot with all exchange positions

        Raises:
            GatewayError: If query fails
        """
        async with self._lock:
            try:
                # Query positions from exchange
                exchange_positions = await self._gateway.query_positions()

                positions = {}
                for pos in exchange_positions:
                    positions[pos.symbol] = self._position_entry(pos)

                return PositionSnapshot(
                    positions=positions,
                    timestamp=datetime.utcnow(),
                    source="exchange",
                )
            except GatewayError as e:
                # REV-024-LOG3: re-raised and logged again by callers — this
                # middle layer's error echo turned one failure into 3-4 lines.
                logger.debug(
                    "Failed to query exchange positions: %s", redact_secrets(str(e))
                )
                raise

    async def _compare_snapshots(
        self,
        local: PositionSnapshot,
        exchange: PositionSnapshot,
    ) -> DiscrepancySet:
        """Compare local and exchange snapshots to detect discrepancies.

        Args:
            local: Local portfolio snapshot
            exchange: Exchange snapshot

        Returns:
            DiscrepancySet with all detected differences
        """
        discrepancies = []

        # Get all symbols from both sides
        all_symbols = set(local.positions.keys()) | set(exchange.positions.keys())

        for symbol in all_symbols:
            local_pos = local.positions.get(symbol)
            exchange_pos = exchange.positions.get(symbol)

            if local_pos and exchange_pos:
                # Both exist - check for mismatch
                local_amount = local_pos.get("amount", 0)
                exchange_amount = exchange_pos.get("amount", 0)

                # Calculate drift in basis points
                if local_amount != 0:
                    drift_bps = abs(local_amount - exchange_amount) / abs(local_amount) * 10000

                    if drift_bps > self._drift_threshold_bps:
                        discrepancies.append(
                            Discrepancy(
                                type=DiscrepancyType.POSITION_MISMATCH,
                                symbol=symbol,
                                local_value=local_amount,
                                exchange_value=exchange_amount,
                                details={
                                    "drift_bps": drift_bps,
                                    "threshold_bps": self._drift_threshold_bps,
                                },
                            )
                        )
            elif local_pos:
                # Orphan position on local side
                discrepancies.append(
                    Discrepancy(
                        type=DiscrepancyType.ORPHAN_POSITION_LOCAL,
                        symbol=symbol,
                        local_value=local_pos.get("amount", 0),
                        exchange_value=None,
                        details={"source": "local_only"},
                    )
                )
            else:
                # Orphan position on exchange side
                discrepancies.append(
                    Discrepancy(
                        type=DiscrepancyType.ORPHAN_POSITION_EXCHANGE,
                        symbol=symbol,
                        local_value=None,
                        exchange_value=(exchange_pos or {}).get("amount", 0),
                        details={"source": "exchange_only"},
                    )
                )

        # Also check for orphan orders
        order_discrepancies = await self._detect_orphan_orders()
        discrepancies.extend(order_discrepancies)

        return DiscrepancySet(items=discrepancies)

    async def _detect_orphan_orders(self) -> list[Discrepancy]:
        """Detect orphan orders (exist on exchange but not tracked locally).

        Returns:
            List of order-related discrepancies
        """
        discrepancies = []

        try:
            # Get symbols we're tracking
            symbols = set()
            symbols_getter = getattr(self._portfolio, "get_symbols", None)
            if callable(symbols_getter):
                symbols = set(symbols_getter())
            else:
                positions_getter = getattr(self._portfolio, "positions", None)
                if positions_getter is not None:
                    symbols = set(dict(positions_getter).keys())

            # Local in-flight order ids: prefer the injected OrderManager
            # (get_open_orders() — the authoritative L5 book), fall back to
            # the portfolio pending ledger when no order manager is injected.
            om_getter = (
                getattr(self._order_manager, "get_open_orders", None)
                if self._order_manager is not None
                else None
            )
            local_orders_by_symbol: dict[str, set[str]] = {}
            if callable(om_getter):
                for order in om_getter():
                    local_orders_by_symbol.setdefault(order.symbol, set()).add(order.order_id)

            for symbol in symbols:
                # Query exchange open orders
                exchange_orders = await self._gateway.query_open_orders(symbol)

                local_order_ids = local_orders_by_symbol.get(symbol, set())
                if not callable(om_getter):
                    pending_getter = getattr(self._portfolio, "get_pending_order_ids", None)
                    if callable(pending_getter):
                        local_order_ids = set(pending_getter(symbol))

                # Check for orphan orders on exchange
                for order in exchange_orders:
                    if order.id not in local_order_ids:
                        # Calculate age
                        age_seconds = time.time() - order.timestamp

                        if age_seconds > self._order_staleness_threshold:
                            discrepancies.append(
                                Discrepancy(
                                    type=DiscrepancyType.ORPHAN_ORDER_EXCHANGE,
                                    symbol=symbol,
                                    local_value=None,
                                    exchange_value=order.filled_amount,
                                    details={
                                        "order_id": order.id,
                                        "age_seconds": age_seconds,
                                        "status": order.status,
                                    },
                                )
                            )
        except GatewayError as e:
            logger.warning(
                "Failed to detect orphan orders: %s", redact_secrets(str(e))
            )

        return discrepancies

    async def _handle_significant_drift(
        self,
        discrepancies: DiscrepancySet,
        reconciliation_id: str,
    ) -> None:
        """Handle significant drift detection.

        Args:
            discrepancies: Detected discrepancies
            reconciliation_id: Reconciliation run ID
        """
        logger.critical(
            "SIGNIFICANT DRIFT DETECTED in %s: %d discrepancies, max severity %.2f",
            reconciliation_id,
            discrepancies.total_discrepancies,
            discrepancies.max_severity,
        )

        # Log critical event
        await self._audit.log_event(
            event_type="RECONCILIATION_DRIFT_DETECTED",
            severity="CRITICAL",
            details={
                "reconciliation_id": reconciliation_id,
                "total_discrepancies": discrepancies.total_discrepancies,
                "max_severity": discrepancies.max_severity,
                "value_at_risk": discrepancies.total_value_at_risk,
            },
        )

        # T021: alert path is intentionally owned by run_daily_reconciliation →
        # _emit_drift_alert (once per run, MonitoringSink). Do not double-send
        # here. Operator pause/kill remains session-level policy, not engine-local.

    async def _emit_drift_alert(
        self,
        discrepancies: DiscrepancySet,
        reconciliation_id: str,
    ) -> None:
        """Send a critical drift alert through the injected MonitoringSink.

        arch-013 seam: ``level`` is a plain string so this layer never
        imports monitoring.alerts — the category tag 'reconciliation_drift'
        mirrors AlertCategory.RECONCILIATION_DRIFT.
        """
        await self._sink.send_alert(
            message=(
                f"[reconciliation_drift] {reconciliation_id}: "
                f"{discrepancies.total_discrepancies} discrepancies, "
                f"max severity {discrepancies.max_severity:.2f}"
            ),
            level="critical",
            extra={
                "category": "reconciliation_drift",
                "reconciliation_id": reconciliation_id,
                "total_discrepancies": discrepancies.total_discrepancies,
                "max_severity": discrepancies.max_severity,
                "value_at_risk": discrepancies.total_value_at_risk,
            },
        )

    async def start_background_loop(self, interval_minutes: float = 5.0) -> None:
        """Start background reconciliation loop.

        Args:
            interval_minutes: Interval between reconciliation runs
        """
        if self._running:
            logger.warning("Background loop already running")
            return

        self._running = True
        interval_seconds = interval_minutes * 60

        async def loop() -> None:
            while self._running:
                try:
                    await self.run_daily_reconciliation()
                except Exception as e:
                    logger.error("Background reconciliation failed: %s", redact_secrets(str(e)))

                await asyncio.sleep(interval_seconds)

        self._background_task = asyncio.create_task(loop())
        logger.info("Background reconciliation loop started (interval=%.1fm)", interval_minutes)

    async def stop_background_loop(self) -> None:
        """Stop background reconciliation loop."""
        self._running = False

        if self._background_task:
            self._background_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._background_task
            self._background_task = None

        logger.info("Background reconciliation loop stopped")
