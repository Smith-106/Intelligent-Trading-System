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
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from quantflow.execution.gateway_base import GatewayBase, GatewayError, OpenOrder
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
    ) -> None:
        """Initialize reconciliation engine.
        
        Args:
            portfolio_manager: L4 portfolio manager for local state
            gateway: Exchange gateway for remote state
            audit_logger: Optional audit logger (creates default if None)
            drift_threshold_bps: Position drift threshold in basis points
            order_staleness_threshold_seconds: Age threshold for orphan orders
        """
        self._portfolio = portfolio_manager
        self._gateway = gateway
        self._audit = audit_logger or AuditLogger(
            secret_key="default-reconciliation-key",  # Should be from config
            enable_file_logging=False,  # Disable for tests
        )
        self._drift_threshold_bps = drift_threshold_bps
        self._order_staleness_threshold = order_staleness_threshold_seconds
        
        self._lock = asyncio.Lock()
        self._background_task: asyncio.Task | None = None
        self._running = False
    
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
            discrepancies = await self._compare_snapshots(
                local_snapshot,
                exchange_snapshot
            )
            
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
            
            logger.info(
                "Reconciliation %s completed: %s",
                reconciliation_id,
                report.summary()
            )
            
            return report
            
        except Exception as e:
            logger.error("Reconciliation %s failed: %s", reconciliation_id, e)
            
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
    
    async def _capture_local_snapshot(self) -> PositionSnapshot:
        """Capture current local portfolio state.
        
        Returns:
            PositionSnapshot with all local positions
        """
        async with self._lock:
            # Get positions from portfolio manager
            # This is a placeholder - actual implementation depends on PortfolioManager API
            positions = {}
            
            # Example: if portfolio has get_positions() method
            if hasattr(self._portfolio, "get_positions"):
                pos_list = self._portfolio.get_positions()
                for pos in pos_list:
                    positions[pos.symbol] = {
                        "amount": pos.amount,
                        "entry_price": pos.entry_price,
                        "unrealized_pnl": pos.unrealized_pnl,
                    }
            
            return PositionSnapshot(
                positions=positions,
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
                    positions[pos.symbol] = {
                        "amount": pos.amount,
                        "entry_price": pos.entry_price,
                        "unrealized_pnl": pos.unrealized_pnl,
                    }
                
                return PositionSnapshot(
                    positions=positions,
                    timestamp=datetime.utcnow(),
                    source="exchange",
                )
            except GatewayError as e:
                logger.error("Failed to query exchange positions: %s", e)
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
                        discrepancies.append(Discrepancy(
                            type=DiscrepancyType.POSITION_MISMATCH,
                            symbol=symbol,
                            local_value=local_amount,
                            exchange_value=exchange_amount,
                            details={
                                "drift_bps": drift_bps,
                                "threshold_bps": self._drift_threshold_bps,
                            },
                        ))
            elif local_pos:
                # Orphan position on local side
                discrepancies.append(Discrepancy(
                    type=DiscrepancyType.ORPHAN_POSITION_LOCAL,
                    symbol=symbol,
                    local_value=local_pos.get("amount", 0),
                    exchange_value=None,
                    details={"source": "local_only"},
                ))
            else:
                # Orphan position on exchange side
                discrepancies.append(Discrepancy(
                    type=DiscrepancyType.ORPHAN_POSITION_EXCHANGE,
                    symbol=symbol,
                    local_value=None,
                    exchange_value=exchange_pos.get("amount", 0),
                    details={"source": "exchange_only"},
                ))
        
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
            if hasattr(self._portfolio, "get_symbols"):
                symbols = self._portfolio.get_symbols()
            
            for symbol in symbols:
                # Query exchange open orders
                exchange_orders = await self._gateway.query_open_orders(symbol)
                
                # Get local pending orders (placeholder - depends on OrderManager API)
                local_order_ids = set()
                if hasattr(self._portfolio, "get_pending_order_ids"):
                    local_order_ids = self._portfolio.get_pending_order_ids(symbol)
                
                # Check for orphan orders on exchange
                for order in exchange_orders:
                    if order.id not in local_order_ids:
                        # Calculate age
                        age_seconds = time.time() - order.timestamp
                        
                        if age_seconds > self._order_staleness_threshold:
                            discrepancies.append(Discrepancy(
                                type=DiscrepancyType.ORPHAN_ORDER_EXCHANGE,
                                symbol=symbol,
                                local_value=None,
                                exchange_value=order.filled_amount,
                                details={
                                    "order_id": order.id,
                                    "age_seconds": age_seconds,
                                    "status": order.status,
                                },
                            ))
        except GatewayError as e:
            logger.warning("Failed to detect orphan orders: %s", e)
        
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
        
        # TODO: Trigger alerts, pause trading, notify operators
        # This would integrate with the alert classification system (G5)
    
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
        
        async def loop():
            while self._running:
                try:
                    await self.run_daily_reconciliation()
                except Exception as e:
                    logger.error("Background reconciliation failed: %s", e)
                
                await asyncio.sleep(interval_seconds)
        
        self._background_task = asyncio.create_task(loop())
        logger.info("Background reconciliation loop started (interval=%.1fm)", interval_minutes)
    
    async def stop_background_loop(self) -> None:
        """Stop background reconciliation loop."""
        self._running = False
        
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
            self._background_task = None
        
        logger.info("Background reconciliation loop stopped")
