"""Unit tests for ReconciliationEngine (ISS-20260720-004).

Tests cover:
- Position drift detection (local vs exchange)
- Orphan position detection (local-only and exchange-only)
- Orphan order detection (exchange-side untracked orders)
- Drift threshold enforcement
- Background loop lifecycle
- Error handling and graceful degradation
- Audit logger integration
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantflow.execution.gateway_base import GatewayError, OpenOrder
from quantflow.reconciliation.engine import ReconciliationEngine
from quantflow.reconciliation.models import (
    DailyReconReport,
    Discrepancy,
    DiscrepancySet,
    DiscrepancyType,
    PositionSnapshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class MockPosition:
    """Mock position object for portfolio/gateway returns."""

    def __init__(self, symbol: str, amount: float, entry_price: float = 100.0):
        self.symbol = symbol
        self.amount = amount
        self.entry_price = entry_price
        self.unrealized_pnl = 0.0


class MockPortfolioManager:
    """Mock L4 PortfolioManager for testing."""

    def __init__(self, positions: list[MockPosition] | None = None):
        self._positions = positions or []
        self._symbols = {p.symbol for p in self._positions}
        self._pending_order_ids: dict[str, set[str]] = {}

    def get_positions(self) -> list[MockPosition]:
        return self._positions

    def get_symbols(self) -> set[str]:
        return self._symbols

    def get_pending_order_ids(self, symbol: str) -> set[str]:
        return self._pending_order_ids.get(symbol, set())

    def add_pending_order(self, symbol: str, order_id: str) -> None:
        self._pending_order_ids.setdefault(symbol, set()).add(order_id)


class MockGateway:
    """Mock GatewayBase for testing."""

    def __init__(
        self,
        positions: list[MockPosition] | None = None,
        open_orders: dict[str, list[OpenOrder]] | None = None,
    ):
        self._positions = positions or []
        self._open_orders = open_orders or {}
        self.query_positions_call_count = 0
        self.query_open_orders_call_count = 0

    async def query_positions(self) -> list[MockPosition]:
        self.query_positions_call_count += 1
        return self._positions

    async def query_open_orders(self, symbol: str) -> list[OpenOrder]:
        self.query_open_orders_call_count += 1
        return self._open_orders.get(symbol, [])


class FailingGateway:
    """Gateway that raises GatewayError on all queries."""

    async def query_positions(self):
        raise GatewayError("Connection lost")

    async def query_open_orders(self, symbol: str):
        raise GatewayError("Connection lost")


@pytest.fixture
def mock_audit_logger():
    """Create a mock audit logger."""
    audit = AsyncMock()
    audit.log_report = AsyncMock()
    audit.log_event = AsyncMock()
    return audit


@pytest.fixture
def basic_engine(mock_audit_logger):
    """Create engine with matching positions (no drift)."""
    portfolio = MockPortfolioManager([
        MockPosition("BTC/USDT", 1.5, entry_price=50000.0),
        MockPosition("ETH/USDT", 10.0, entry_price=3000.0),
    ])
    gateway = MockGateway(positions=[
        MockPosition("BTC/USDT", 1.5, entry_price=50000.0),
        MockPosition("ETH/USDT", 10.0, entry_price=3000.0),
    ])
    return ReconciliationEngine(
        portfolio_manager=portfolio,
        gateway=gateway,
        audit_logger=mock_audit_logger,
        drift_threshold_bps=100.0,
    )


# ---------------------------------------------------------------------------
# Test: Position Drift Detection
# ---------------------------------------------------------------------------


class TestPositionDriftDetection:
    """Tests for position mismatch detection between local and exchange."""

    @pytest.mark.asyncio
    async def test_no_drift_when_positions_match(self, basic_engine, mock_audit_logger):
        """Reconciliation passes when local and exchange positions are identical."""
        report = await basic_engine.run_daily_reconciliation()

        assert report.status == "completed"
        assert report.passed is True
        assert report.discrepancies.total_discrepancies == 0
        assert report.has_critical_issues is False
        mock_audit_logger.log_report.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_drift_detected_above_threshold(self, mock_audit_logger):
        """Position drift above threshold (100 bps) generates discrepancy."""
        portfolio = MockPortfolioManager([
            MockPosition("BTC/USDT", 1.0),  # Local: 1.0 BTC
        ])
        gateway = MockGateway(positions=[
            MockPosition("BTC/USDT", 1.02),  # Exchange: 1.02 BTC (2% drift = 200 bps)
        ])
        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
            drift_threshold_bps=100.0,
        )

        report = await engine.run_daily_reconciliation()

        assert report.status == "completed"
        assert report.discrepancies.total_discrepancies >= 1
        mismatch = report.discrepancies.filter_by_type(DiscrepancyType.POSITION_MISMATCH)
        assert len(mismatch) == 1
        assert mismatch[0].symbol == "BTC/USDT"
        assert mismatch[0].details["drift_bps"] == pytest.approx(200.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_drift_below_threshold_ignored(self, mock_audit_logger):
        """Position drift below threshold does not generate discrepancy."""
        portfolio = MockPortfolioManager([
            MockPosition("BTC/USDT", 1.0),
        ])
        gateway = MockGateway(positions=[
            MockPosition("BTC/USDT", 1.005),  # 0.5% drift = 50 bps < 100 bps
        ])
        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
            drift_threshold_bps=100.0,
        )

        report = await engine.run_daily_reconciliation()

        mismatch = report.discrepancies.filter_by_type(DiscrepancyType.POSITION_MISMATCH)
        assert len(mismatch) == 0

    @pytest.mark.asyncio
    async def test_custom_threshold_enforcement(self, mock_audit_logger):
        """Custom drift threshold is properly enforced."""
        portfolio = MockPortfolioManager([MockPosition("BTC/USDT", 1.0)])
        gateway = MockGateway(positions=[MockPosition("BTC/USDT", 1.005)])  # 50 bps

        # With 30 bps threshold → should detect
        engine_strict = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
            drift_threshold_bps=30.0,
        )
        report = await engine_strict.run_daily_reconciliation()
        assert report.discrepancies.total_discrepancies >= 1

        # With 200 bps threshold → should NOT detect
        engine_lenient = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
            drift_threshold_bps=200.0,
        )
        report = await engine_lenient.run_daily_reconciliation()
        mismatch = report.discrepancies.filter_by_type(DiscrepancyType.POSITION_MISMATCH)
        assert len(mismatch) == 0


# ---------------------------------------------------------------------------
# Test: Orphan Position Detection
# ---------------------------------------------------------------------------


class TestOrphanPositionDetection:
    """Tests for orphan positions (exist on one side only)."""

    @pytest.mark.asyncio
    async def test_orphan_position_local_only(self, mock_audit_logger):
        """Position tracked locally but not on exchange is flagged."""
        portfolio = MockPortfolioManager([
            MockPosition("BTC/USDT", 1.0),
            MockPosition("SOL/USDT", 50.0),  # Only local
        ])
        gateway = MockGateway(positions=[
            MockPosition("BTC/USDT", 1.0),
            # SOL/USDT missing from exchange
        ])
        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
        )

        report = await engine.run_daily_reconciliation()

        orphans = report.discrepancies.filter_by_type(DiscrepancyType.ORPHAN_POSITION_LOCAL)
        assert len(orphans) == 1
        assert orphans[0].symbol == "SOL/USDT"
        assert orphans[0].severity_score == 1.0  # Orphans are max severity

    @pytest.mark.asyncio
    async def test_orphan_position_exchange_only(self, mock_audit_logger):
        """Position on exchange but not tracked locally is flagged."""
        portfolio = MockPortfolioManager([
            MockPosition("BTC/USDT", 1.0),
            # ETH/USDT not tracked locally
        ])
        gateway = MockGateway(positions=[
            MockPosition("BTC/USDT", 1.0),
            MockPosition("ETH/USDT", 5.0),  # Only on exchange
        ])
        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
        )

        report = await engine.run_daily_reconciliation()

        orphans = report.discrepancies.filter_by_type(DiscrepancyType.ORPHAN_POSITION_EXCHANGE)
        assert len(orphans) == 1
        assert orphans[0].symbol == "ETH/USDT"
        assert orphans[0].exchange_value == 5.0


# ---------------------------------------------------------------------------
# Test: Orphan Order Detection
# ---------------------------------------------------------------------------


class TestOrphanOrderDetection:
    """Tests for orphan order detection (exchange orders not tracked locally)."""

    @pytest.mark.asyncio
    async def test_orphan_order_detected_when_stale(self, mock_audit_logger):
        """Exchange order not tracked locally and older than threshold is flagged."""
        portfolio = MockPortfolioManager([MockPosition("BTC/USDT", 1.0)])
        # Order created 10 minutes ago (600s > 300s threshold)
        stale_order = OpenOrder(
            id="orphan-order-001",
            symbol="BTC/USDT",
            side="buy",
            order_type="limit",
            price=49000.0,
            filled_amount=0.0,
            status="open",
            timestamp=time.time() - 600,  # 10 minutes ago
        )
        gateway = MockGateway(
            positions=[MockPosition("BTC/USDT", 1.0)],
            open_orders={"BTC/USDT": [stale_order]},
        )
        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
            order_staleness_threshold_seconds=300.0,
        )

        report = await engine.run_daily_reconciliation()

        orphans = report.discrepancies.filter_by_type(DiscrepancyType.ORPHAN_ORDER_EXCHANGE)
        assert len(orphans) == 1
        assert orphans[0].details["order_id"] == "orphan-order-001"
        assert orphans[0].details["age_seconds"] > 300

    @pytest.mark.asyncio
    async def test_recent_order_not_flagged(self, mock_audit_logger):
        """Exchange order younger than staleness threshold is not flagged."""
        portfolio = MockPortfolioManager([MockPosition("BTC/USDT", 1.0)])
        recent_order = OpenOrder(
            id="recent-order-001",
            symbol="BTC/USDT",
            side="sell",
            order_type="limit",
            price=51000.0,
            filled_amount=0.0,
            status="open",
            timestamp=time.time() - 60,  # 1 minute ago (< 300s threshold)
        )
        gateway = MockGateway(
            positions=[MockPosition("BTC/USDT", 1.0)],
            open_orders={"BTC/USDT": [recent_order]},
        )
        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
            order_staleness_threshold_seconds=300.0,
        )

        report = await engine.run_daily_reconciliation()

        orphans = report.discrepancies.filter_by_type(DiscrepancyType.ORPHAN_ORDER_EXCHANGE)
        assert len(orphans) == 0

    @pytest.mark.asyncio
    async def test_tracked_order_not_flagged(self, mock_audit_logger):
        """Exchange order that IS tracked locally is not flagged as orphan."""
        portfolio = MockPortfolioManager([MockPosition("BTC/USDT", 1.0)])
        portfolio.add_pending_order("BTC/USDT", "tracked-order-001")

        tracked_order = OpenOrder(
            id="tracked-order-001",
            symbol="BTC/USDT",
            side="buy",
            order_type="limit",
            price=49500.0,
            filled_amount=0.5,
            status="open",
            timestamp=time.time() - 600,  # Old but tracked
        )
        gateway = MockGateway(
            positions=[MockPosition("BTC/USDT", 1.0)],
            open_orders={"BTC/USDT": [tracked_order]},
        )
        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
        )

        report = await engine.run_daily_reconciliation()

        orphans = report.discrepancies.filter_by_type(DiscrepancyType.ORPHAN_ORDER_EXCHANGE)
        assert len(orphans) == 0


# ---------------------------------------------------------------------------
# Test: Error Handling & Graceful Degradation
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for error handling and graceful degradation."""

    @pytest.mark.asyncio
    async def test_gateway_failure_produces_failed_report(self, mock_audit_logger):
        """GatewayError produces a failed report rather than crashing."""
        portfolio = MockPortfolioManager([MockPosition("BTC/USDT", 1.0)])
        gateway = FailingGateway()
        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
        )

        report = await engine.run_daily_reconciliation()

        assert report.status == "failed"
        assert report.error_message is not None
        assert "Connection lost" in report.error_message

    @pytest.mark.asyncio
    async def test_orphan_order_detection_survives_gateway_error(self, mock_audit_logger):
        """Orphan order detection gracefully handles GatewayError."""
        portfolio = MockPortfolioManager([MockPosition("BTC/USDT", 1.0)])
        gateway = MockGateway(positions=[MockPosition("BTC/USDT", 1.0)])

        # Make query_open_orders fail
        async def failing_query(symbol):
            raise GatewayError("Rate limited")

        gateway.query_open_orders = failing_query

        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
        )

        # Should not raise — orphan detection catches GatewayError
        report = await engine.run_daily_reconciliation()
        assert report.status == "completed"


# ---------------------------------------------------------------------------
# Test: Background Loop Lifecycle
# ---------------------------------------------------------------------------


class TestBackgroundLoop:
    """Tests for background reconciliation loop."""

    @pytest.mark.asyncio
    async def test_background_loop_starts_and_stops(self, basic_engine):
        """Background loop can be started and stopped cleanly."""
        await basic_engine.start_background_loop(interval_minutes=0.01)  # ~0.6s
        assert basic_engine._running is True
        assert basic_engine._background_task is not None

        await asyncio.sleep(0.1)  # Let it run at least once

        await basic_engine.stop_background_loop()
        assert basic_engine._running is False
        assert basic_engine._background_task is None

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self, basic_engine):
        """Starting loop twice does not create duplicate tasks."""
        await basic_engine.start_background_loop(interval_minutes=1.0)
        first_task = basic_engine._background_task

        await basic_engine.start_background_loop(interval_minutes=1.0)
        assert basic_engine._background_task is first_task  # Same task

        await basic_engine.stop_background_loop()


# ---------------------------------------------------------------------------
# Test: Report Structure & Audit Integration
# ---------------------------------------------------------------------------


class TestReportAndAudit:
    """Tests for report generation and audit logger integration."""

    @pytest.mark.asyncio
    async def test_report_contains_valid_metadata(self, basic_engine):
        """Report includes reconciliation_id, duration, and timestamps."""
        report = await basic_engine.run_daily_reconciliation()

        assert report.reconciliation_id.startswith("RECON-")
        assert report.duration_seconds >= 0
        assert report.reconciled_at is not None
        assert report.local_snapshot.source == "local"
        assert report.exchange_snapshot.source == "exchange"

    @pytest.mark.asyncio
    async def test_critical_drift_triggers_audit_event(self, mock_audit_logger):
        """Critical drift (>0.8 severity) triggers audit event logging."""
        portfolio = MockPortfolioManager([
            MockPosition("BTC/USDT", 1.0),
        ])
        gateway = MockGateway(positions=[
            # Exchange has position we don't track → orphan → severity 1.0
            MockPosition("BTC/USDT", 1.0),
            MockPosition("DOGE/USDT", 100000.0),
        ])
        engine = ReconciliationEngine(
            portfolio_manager=portfolio,
            gateway=gateway,
            audit_logger=mock_audit_logger,
        )

        report = await engine.run_daily_reconciliation()

        assert report.has_critical_issues is True
        mock_audit_logger.log_event.assert_awaited_once()
        call_kwargs = mock_audit_logger.log_event.call_args[1]
        assert call_kwargs["severity"] == "CRITICAL"

    @pytest.mark.asyncio
    async def test_report_summary_format(self, basic_engine):
        """Report summary() produces human-readable string."""
        report = await basic_engine.run_daily_reconciliation()
        summary = report.summary()

        assert "Reconciliation" in summary
        assert "RECON-" in summary
        assert "discrepancies" in summary


# ---------------------------------------------------------------------------
# Test: DiscrepancySet Aggregate Metrics
# ---------------------------------------------------------------------------


class TestDiscrepancySetMetrics:
    """Tests for DiscrepancySet aggregate calculations."""

    def test_empty_set_has_zero_metrics(self):
        """Empty DiscrepancySet has zero totals."""
        ds = DiscrepancySet()
        assert ds.total_discrepancies == 0
        assert ds.max_severity == 0.0
        assert ds.total_value_at_risk == 0.0

    def test_aggregate_metrics_calculated(self):
        """DiscrepancySet correctly aggregates severity and value at risk."""
        items = [
            Discrepancy(
                type=DiscrepancyType.POSITION_MISMATCH,
                symbol="BTC/USDT",
                local_value=1.0,
                exchange_value=1.1,
            ),
            Discrepancy(
                type=DiscrepancyType.ORPHAN_POSITION_EXCHANGE,
                symbol="ETH/USDT",
                local_value=None,
                exchange_value=5.0,
            ),
        ]
        ds = DiscrepancySet(items=items)

        assert ds.total_discrepancies == 2
        assert ds.max_severity == 1.0  # Orphan has severity 1.0
        assert ds.total_value_at_risk > 0

    def test_filter_by_type(self):
        """filter_by_type returns only matching discrepancies."""
        items = [
            Discrepancy(type=DiscrepancyType.POSITION_MISMATCH, symbol="BTC/USDT"),
            Discrepancy(type=DiscrepancyType.ORPHAN_POSITION_LOCAL, symbol="SOL/USDT"),
            Discrepancy(type=DiscrepancyType.POSITION_MISMATCH, symbol="ETH/USDT"),
        ]
        ds = DiscrepancySet(items=items)

        mismatches = ds.filter_by_type(DiscrepancyType.POSITION_MISMATCH)
        assert len(mismatches) == 2

        orphans = ds.filter_by_type(DiscrepancyType.ORPHAN_POSITION_LOCAL)
        assert len(orphans) == 1

    def test_filter_by_severity(self):
        """filter_by_severity returns items above threshold."""
        items = [
            Discrepancy(
                type=DiscrepancyType.POSITION_MISMATCH,
                symbol="BTC/USDT",
                local_value=1.0,
                exchange_value=1.01,  # 1% diff → severity 0.01
            ),
            Discrepancy(
                type=DiscrepancyType.ORPHAN_POSITION_EXCHANGE,
                symbol="ETH/USDT",
                local_value=None,
                exchange_value=5.0,  # Orphan → severity 1.0
            ),
        ]
        ds = DiscrepancySet(items=items)

        critical = ds.filter_by_severity(0.5)
        assert len(critical) == 1
        assert critical[0].symbol == "ETH/USDT"
