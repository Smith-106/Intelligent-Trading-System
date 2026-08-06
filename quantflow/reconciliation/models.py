"""Data models for reconciliation engine.

Defines the core data structures used for position snapshots,
discrepancy detection, and reconciliation reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DiscrepancyType(Enum):
    """Types of discrepancies that can be detected during reconciliation."""

    POSITION_MISMATCH = "position_mismatch"
    ORPHAN_POSITION_LOCAL = "orphan_position_local"
    ORPHAN_POSITION_EXCHANGE = "orphan_position_exchange"
    ORDER_MISMATCH = "order_mismatch"
    ORPHAN_ORDER_LOCAL = "orphan_order_local"
    ORPHAN_ORDER_EXCHANGE = "orphan_order_exchange"


@dataclass
class PositionSnapshot:
    """Snapshot of portfolio positions at a point in time.

    Used to capture state before/after reconciliation for comparison.
    """

    positions: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = "unknown"  # "local" or "exchange"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "positions": {k: str(v) for k, v in self.positions.items()},
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PositionSnapshot:
        """Create from dictionary."""
        return cls(
            positions=data.get("positions", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            source=data.get("source", "unknown"),
        )


@dataclass
class Discrepancy:
    """A single discrepancy detected during reconciliation.

    Represents a difference between local state and exchange state.
    """

    type: DiscrepancyType
    symbol: str
    local_value: float | None = None
    exchange_value: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    detected_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def severity_score(self) -> float:
        """Calculate severity score (0-1) based on discrepancy magnitude."""
        if self.local_value is None or self.exchange_value is None:
            return 1.0  # Orphan positions are high severity

        if self.local_value == 0:
            return 1.0 if self.exchange_value != 0 else 0.0

        relative_diff = abs(self.local_value - self.exchange_value) / abs(self.local_value)
        return min(relative_diff, 1.0)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type.value,
            "symbol": self.symbol,
            "local_value": self.local_value,
            "exchange_value": self.exchange_value,
            "details": self.details,
            "detected_at": self.detected_at.isoformat(),
            "severity_score": self.severity_score,
        }


@dataclass
class DiscrepancySet:
    """Collection of discrepancies detected in a reconciliation run.

    Provides aggregate metrics and filtering capabilities.
    """

    items: list[Discrepancy] = field(default_factory=list)
    total_discrepancies: int = 0
    max_severity: float = 0.0
    total_value_at_risk: float = 0.0

    def __post_init__(self) -> None:
        """Calculate aggregate metrics after initialization."""
        self.total_discrepancies = len(self.items)
        if self.items:
            self.max_severity = max(d.severity_score for d in self.items)
            self.total_value_at_risk = sum(
                abs(d.local_value or 0) + abs(d.exchange_value or 0) for d in self.items
            )

    def filter_by_type(self, discrepancy_type: DiscrepancyType) -> list[Discrepancy]:
        """Filter discrepancies by type."""
        return [d for d in self.items if d.type == discrepancy_type]

    def filter_by_severity(self, min_severity: float) -> list[Discrepancy]:
        """Filter discrepancies by minimum severity score."""
        return [d for d in self.items if d.severity_score >= min_severity]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_discrepancies": self.total_discrepancies,
            "max_severity": self.max_severity,
            "total_value_at_risk": self.total_value_at_risk,
            "items": [d.to_dict() for d in self.items],
        }


@dataclass
class DailyReconReport:
    """Complete report from a daily reconciliation run.

    Contains snapshots, discrepancies, and metadata for audit purposes.
    """

    local_snapshot: PositionSnapshot
    exchange_snapshot: PositionSnapshot
    discrepancies: DiscrepancySet
    reconciled_at: datetime = field(default_factory=datetime.utcnow)
    reconciliation_id: str = ""
    duration_seconds: float = 0.0
    status: str = "completed"  # "completed", "failed", "partial"
    error_message: str | None = None

    @property
    def has_critical_issues(self) -> bool:
        """Check if report contains critical discrepancies."""
        return self.discrepancies.max_severity > 0.8

    @property
    def passed(self) -> bool:
        """Check if reconciliation passed (no critical issues)."""
        return not self.has_critical_issues and self.status == "completed"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "reconciliation_id": self.reconciliation_id,
            "reconciled_at": self.reconciled_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "error_message": self.error_message,
            "local_snapshot": self.local_snapshot.to_dict(),
            "exchange_snapshot": self.exchange_snapshot.to_dict(),
            "discrepancies": self.discrepancies.to_dict(),
            "has_critical_issues": self.has_critical_issues,
            "passed": self.passed,
        }

    def summary(self) -> str:
        """Generate human-readable summary."""
        status_icon = "✅" if self.passed else "❌"
        return (
            f"{status_icon} Reconciliation {self.reconciliation_id}: "
            f"{self.discrepancies.total_discrepancies} discrepancies, "
            f"max severity {self.discrepancies.max_severity:.2f}, "
            f"value at risk ${self.discrepancies.total_value_at_risk:,.2f}"
        )
