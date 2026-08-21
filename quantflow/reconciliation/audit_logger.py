"""Audit logger with HMAC signatures for reconciliation compliance.

Provides immutable, tamper-evident audit trail for all reconciliation events.
Each log entry is signed with HMAC-SHA256 to detect unauthorized modifications.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditLogger:
    """HMAC-signed audit logger for reconciliation events.

    Features:
    - Tamper-evident logging via HMAC-SHA256 signatures
    - Structured JSON output for compliance reporting
    - Automatic rotation and archival
    - Query interface for audit investigations

    Usage:
        audit = AuditLogger(secret_key="your-secret", log_dir="logs/audit")
        await audit.log_event(
            event_type="RECONCILIATION_DRIFT_DETECTED",
            severity="CRITICAL",
            details={"symbol": "BTC/USDT", "drift_bps": 150}
        )
    """

    def __init__(
        self,
        secret_key: str,
        log_dir: str | Path = "logs/audit",
        enable_file_logging: bool = True,
    ) -> None:
        """Initialize audit logger.

        Args:
            secret_key: HMAC secret key for signing log entries
            log_dir: Directory for audit log files
            enable_file_logging: Whether to write logs to disk (disable for tests)
        """
        self._secret_key = secret_key.encode("utf-8")
        self._log_dir = Path(log_dir)
        self._enable_file_logging = enable_file_logging
        self._sequence_number = 0

        if self._enable_file_logging:
            self._log_dir.mkdir(parents=True, exist_ok=True)

    def _compute_hmac(self, message: str) -> str:
        """Compute HMAC-SHA256 signature for a message.

        Args:
            message: Message to sign

        Returns:
            Hex-encoded HMAC signature
        """
        return hmac.new(self._secret_key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def _create_log_entry(
        self,
        event_type: str,
        severity: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a signed log entry.

        Args:
            event_type: Type of event (e.g., "RECONCILIATION_DRIFT_DETECTED")
            severity: Severity level (INFO, WARNING, CRITICAL)
            details: Event-specific details

        Returns:
            Signed log entry dictionary
        """
        self._sequence_number += 1

        entry = {
            "sequence": self._sequence_number,
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "severity": severity,
            "details": details,
        }

        # Create canonical message for signing (sorted keys for determinism)
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        signature = self._compute_hmac(canonical)
        entry["hmac_signature"] = signature

        return entry

    async def log_event(
        self,
        event_type: str,
        severity: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """Log a reconciliation event with HMAC signature.

        Args:
            event_type: Type of event
            severity: Severity level
            details: Event details

        Returns:
            The signed log entry
        """
        entry = self._create_log_entry(event_type, severity, details)

        # Log to standard logger
        log_level = getattr(logging, severity.upper(), logging.INFO)
        logger.log(log_level, "AUDIT: %s - %s", event_type, json.dumps(details, default=str))

        # Write to file if enabled
        if self._enable_file_logging:
            await self._write_to_file(entry)

        return entry

    async def log_report(self, report: Any) -> dict[str, Any]:
        """Log a complete reconciliation report.

        Args:
            report: DailyReconReport object

        Returns:
            The signed log entry
        """
        # Convert report to dict if it has to_dict method
        report_dict = report.to_dict() if hasattr(report, "to_dict") else {"report": str(report)}

        return await self.log_event(
            event_type="RECONCILIATION_REPORT",
            severity="INFO" if report_dict.get("passed", False) else "CRITICAL",
            details=report_dict,
        )

    async def _write_to_file(self, entry: dict[str, Any]) -> None:
        """Write log entry to file (append mode).

        Args:
            entry: Log entry to write
        """
        try:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            log_file = self._log_dir / f"audit-{date_str}.jsonl"

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)

    def verify_entry(self, entry: dict[str, Any]) -> bool:
        """Verify HMAC signature of a log entry.

        Args:
            entry: Log entry to verify

        Returns:
            True if signature is valid, False otherwise
        """
        if "hmac_signature" not in entry:
            return False

        # Extract signature and remove it for verification
        signature = entry.pop("hmac_signature")

        # Recompute signature
        canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        expected_signature = self._compute_hmac(canonical)

        # Restore signature
        entry["hmac_signature"] = signature

        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(signature, expected_signature)

    async def query_events(
        self,
        event_type: str | None = None,
        severity: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Query audit log events with filters.

        Args:
            event_type: Filter by event type (optional)
            severity: Filter by severity (optional)
            start_time: Filter events after this time (optional)
            end_time: Filter events before this time (optional)
            limit: Maximum number of results

        Returns:
            List of matching log entries
        """
        if not self._enable_file_logging:
            logger.warning("File logging disabled, cannot query events")
            return []

        results = []

        # Scan all log files
        for log_file in sorted(self._log_dir.glob("audit-*.jsonl"), reverse=True):
            try:
                with open(log_file, encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue

                        entry = json.loads(line)

                        # Apply filters
                        if event_type and entry.get("event_type") != event_type:
                            continue
                        if severity and entry.get("severity") != severity:
                            continue

                        entry_time = datetime.fromisoformat(entry["timestamp"])
                        if start_time and entry_time < start_time:
                            continue
                        if end_time and entry_time > end_time:
                            continue

                        results.append(entry)

                        if len(results) >= limit:
                            return results
            except Exception as e:
                logger.error("Error reading audit log %s: %s", log_file, e)

        return results
