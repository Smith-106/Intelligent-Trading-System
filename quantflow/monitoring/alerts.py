"""Alert manager with Telegram and LINE notification support."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from enum import StrEnum
from typing import Any

import aiohttp

from quantflow.common.redaction import redact_secrets
from quantflow.common.url_safety import UnsafeUrlError, validate_outbound_url

logger = logging.getLogger(__name__)


def _safe_alert_error(exc: BaseException) -> str:
    """Redact secrets from an alert-send exception before logging.

    aiohttp connection/ClientConnectorError exceptions embed the request URL in
    ``str(e)``, and the Telegram URL is
    ``https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage`` — so a
    failed send would otherwise write the bot token to the server log. The LINE
    path can echo the ``Authorization: Bearer {token}`` header. Route every
    alert error through the centralized scrubber (ISS-002 single audit face)
    so the token shape is stripped, matching okx_gateway._safe_error
    (odyssey-review SEC finding, CWE-532).
    """
    return redact_secrets(str(exc))


class AlertLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCategory(StrEnum):
    """Enhanced alert categories for smart routing (G5)."""
    
    # System/Infrastructure
    SYSTEM_HEALTH = "system_health"
    CONNECTIVITY = "connectivity"
    PERFORMANCE = "performance"
    
    # Trading Operations
    EXECUTION_FAILURE = "execution_failure"
    ORDER_TIMEOUT = "order_timeout"
    RECONCILIATION_DRIFT = "reconciliation_drift"
    ORPHAN_ORDER = "orphan_order"
    
    # Risk Management
    RISK_THRESHOLD = "risk_threshold"
    POSITION_LIMIT = "position_limit"
    DRAWDOWN_BREACH = "drawdown_breach"
    VAR_BREACH = "var_breach"
    
    # Data Quality
    DATA_STALENESS = "data_staleness"
    DATA_ANOMALY = "data_anomaly"
    FEED_INTERRUPT = "feed_interrupt"
    
    # Strategy
    SIGNAL_GENERATION = "signal_generation"
    STRATEGY_ERROR = "strategy_error"


class AlertPriority(StrEnum):
    """Alert priority levels for routing decisions (G5)."""
    
    P0_EMERGENCY = "p0_emergency"  # Immediate page, trading halt
    P1_HIGH = "p1_high"  # Page within 5 minutes
    P2_MEDIUM = "p2_medium"  # Notify within 30 minutes
    P3_LOW = "p3_low"  # Batch notification, next business day


# ---------------------------------------------------------------------------
# Alert Routing Matrix (ISS-20260802-005)
# ---------------------------------------------------------------------------

# Default routing rules: maps (category, priority) → notification channels.
# Channels: "telegram", "line", "webhook", "pagerduty" (future)
# Override via YAML config: quantflow/config/alert_routing.yaml
ALERT_ROUTING: dict[tuple[AlertCategory, AlertPriority], list[str]] = {
    # P0 Emergency — all channels, immediate
    (AlertCategory.RECONCILIATION_DRIFT, AlertPriority.P0_EMERGENCY): ["telegram", "webhook"],
    (AlertCategory.EXECUTION_FAILURE, AlertPriority.P0_EMERGENCY): ["telegram", "webhook"],
    (AlertCategory.DRAWDOWN_BREACH, AlertPriority.P0_EMERGENCY): ["telegram", "line", "webhook"],
    (AlertCategory.FEED_INTERRUPT, AlertPriority.P0_EMERGENCY): ["telegram", "webhook"],
    # P1 High — telegram + webhook
    (AlertCategory.ORPHAN_ORDER, AlertPriority.P1_HIGH): ["telegram", "webhook"],
    (AlertCategory.ORDER_TIMEOUT, AlertPriority.P1_HIGH): ["telegram"],
    (AlertCategory.CONNECTIVITY, AlertPriority.P1_HIGH): ["telegram"],
    (AlertCategory.VAR_BREACH, AlertPriority.P1_HIGH): ["telegram", "webhook"],
    # P2 Medium — telegram only
    (AlertCategory.DATA_STALENESS, AlertPriority.P2_MEDIUM): ["telegram"],
    (AlertCategory.DATA_ANOMALY, AlertPriority.P2_MEDIUM): ["telegram"],
    (AlertCategory.PERFORMANCE, AlertPriority.P2_MEDIUM): ["telegram"],
    (AlertCategory.POSITION_LIMIT, AlertPriority.P2_MEDIUM): ["telegram"],
    # P3 Low — webhook batch only
    (AlertCategory.SYSTEM_HEALTH, AlertPriority.P3_LOW): ["webhook"],
    (AlertCategory.SIGNAL_GENERATION, AlertPriority.P3_LOW): ["webhook"],
    (AlertCategory.STRATEGY_ERROR, AlertPriority.P3_LOW): ["webhook"],
}

# Default channels when no specific route matches
DEFAULT_ALERT_CHANNELS: list[str] = ["telegram"]


def resolve_alert_channels(
    category: AlertCategory,
    priority: AlertPriority,
) -> list[str]:
    """Resolve notification channels for a given alert category + priority.

    Uses ALERT_ROUTING matrix with fallback to DEFAULT_ALERT_CHANNELS.

    Args:
        category: Alert category enum
        priority: Alert priority enum

    Returns:
        List of channel names to notify
    """
    return ALERT_ROUTING.get((category, priority), DEFAULT_ALERT_CHANNELS)


class AlertDeduplicator:
    """Sliding window alert deduplication (ISS-20260802-005).

    Prevents alert fatigue by suppressing duplicate alerts within a
    configurable time window. Each unique alert key (category + symbol)
    is tracked independently.

    Usage:
        dedup = AlertDeduplicator(window_seconds=300)  # 5 min window

        if dedup.should_send("reconciliation_drift:BTC/USDT"):
            await alert_manager.send(...)
        # Second identical alert within 5 min → suppressed
    """

    def __init__(self, window_seconds: float = 300.0) -> None:
        """Initialize deduplicator.

        Args:
            window_seconds: Time window for deduplication (default 5 min)
        """
        self._window = window_seconds
        self._seen: dict[str, list[float]] = defaultdict(list)
        self._suppressed_count = 0

    def should_send(self, alert_key: str) -> bool:
        """Check if alert should be sent (not a duplicate within window).

        Args:
            alert_key: Unique key for the alert (e.g., "category:symbol")

        Returns:
            True if alert should be sent, False if suppressed as duplicate
        """
        now = time.time()

        # Prune expired entries
        self._seen[alert_key] = [
            t for t in self._seen[alert_key] if now - t < self._window
        ]

        if self._seen[alert_key]:
            # Duplicate within window — suppress
            self._suppressed_count += 1
            return False

        # Record and allow
        self._seen[alert_key].append(now)
        return True

    def make_key(self, category: AlertCategory, symbol: str = "") -> str:
        """Generate a deduplication key from category and symbol.

        Args:
            category: Alert category
            symbol: Trading pair (optional)

        Returns:
            Dedup key string
        """
        return f"{category.value}:{symbol}" if symbol else category.value

    @property
    def suppressed_count(self) -> int:
        """Total number of alerts suppressed since initialization."""
        return self._suppressed_count

    def reset(self) -> None:
        """Clear all deduplication state."""
        self._seen.clear()
        self._suppressed_count = 0


class AlertManager:
    """Manage alerts with Telegram/LINE/webhook notifications.

    Configure via environment variables or config:
    - TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
    - LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID
    - WEBHOOK_URL (generic webhook)

    Enhanced with smart routing (ISS-20260802-005):
    - ALERT_ROUTING matrix maps (category, priority) → channels
    - AlertDeduplicator prevents alert fatigue
    """

    def __init__(
        self,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        line_token: str = "",
        line_user_id: str = "",
        webhook_url: str = "",
        dedup_window_seconds: float = 300.0,
    ):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.line_token = line_token
        self.line_user_id = line_user_id
        self.webhook_url = webhook_url
        self._dedup = AlertDeduplicator(window_seconds=dedup_window_seconds)

    async def send(
        self,
        message: str,
        level: AlertLevel = AlertLevel.INFO,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        """Send alert to all configured channels.

        Returns dict of {channel: success} for each attempted delivery.
        """
        results: dict[str, bool] = {}
        log_fn = {
            AlertLevel.INFO: logger.info,
            AlertLevel.WARNING: logger.warning,
            AlertLevel.CRITICAL: logger.critical,
        }
        log_fn[level]("Alert [%s]: %s", level.value, message)

        if self.telegram_token:
            results["telegram"] = await self._send_telegram(message, level, extra)
        if self.line_token:
            results["line"] = await self._send_line(message, level)
        if self.webhook_url:
            results["webhook"] = await self._send_webhook(message, level, extra)

        return results

    async def send_routed(
        self,
        message: str,
        category: AlertCategory,
        priority: AlertPriority,
        symbol: str = "",
        level: AlertLevel | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        """Send alert with smart routing and deduplication (ISS-20260802-005).

        Routes alert to appropriate channels based on category + priority,
        and suppresses duplicates within the dedup window.

        Args:
            message: Alert message text
            category: Alert category for routing
            priority: Alert priority for routing
            symbol: Trading pair (for dedup key)
            level: AlertLevel override (inferred from priority if None)
            extra: Additional context dict

        Returns:
            Dict of {channel: success} for attempted deliveries.
            Empty dict if alert was deduplicated (suppressed).
        """
        # Deduplication check
        dedup_key = self._dedup.make_key(category, symbol)
        if not self._dedup.should_send(dedup_key):
            logger.debug(
                "Alert suppressed (dedup): %s [%s/%s]",
                dedup_key, category.value, priority.value,
            )
            return {}  # Suppressed

        # Infer AlertLevel from priority if not provided
        if level is None:
            level = {
                AlertPriority.P0_EMERGENCY: AlertLevel.CRITICAL,
                AlertPriority.P1_HIGH: AlertLevel.CRITICAL,
                AlertPriority.P2_MEDIUM: AlertLevel.WARNING,
                AlertPriority.P3_LOW: AlertLevel.INFO,
            }[priority]

        # Resolve target channels
        channels = resolve_alert_channels(category, priority)

        # Send only to routed channels
        results: dict[str, bool] = {}
        enriched_extra = {
            **(extra or {}),
            "category": category.value,
            "priority": priority.value,
            "symbol": symbol,
        }

        if "telegram" in channels and self.telegram_token:
            results["telegram"] = await self._send_telegram(message, level, enriched_extra)
        if "line" in channels and self.line_token:
            results["line"] = await self._send_line(message, level)
        if "webhook" in channels and self.webhook_url:
            results["webhook"] = await self._send_webhook(message, level, enriched_extra)

        return results

    @property
    def deduplicator(self) -> AlertDeduplicator:
        """Access the alert deduplicator for metrics/inspection."""
        return self._dedup

    async def _send_telegram(
        self,
        message: str,
        level: AlertLevel,
        extra: dict[str, Any] | None,
    ) -> bool:
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        text = f"[{level.value.upper()}] {message}"
        if extra:
            text += f"\n{json.dumps(extra, default=str)}"
        payload = {"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "HTML"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error("Telegram alert failed: %s", _safe_alert_error(e))
            return False

    async def _send_line(self, message: str, level: AlertLevel) -> bool:
        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Authorization": f"Bearer {self.line_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "to": self.line_user_id,
            "messages": [{"type": "text", "text": f"[{level.value.upper()}] {message}"}],
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error("LINE alert failed: %s", _safe_alert_error(e))
            return False

    async def _send_webhook(
        self,
        message: str,
        level: AlertLevel,
        extra: dict[str, Any] | None,
    ) -> bool:
        payload = {"level": level.value, "message": message, **(extra or {})}
        # ISS-003 (SEC-010): SSRF guard. The generic webhook URL is operator-
        # configurable; without scheme/host validation it is a pure SSRF sink
        # (a misconfigured webhook_url pointing at 127.0.0.1, a private host, or
        # a cloud-metadata endpoint would let an attacker probe the internal
        # network). Reject non-https and non-public hosts before any HTTP call.
        try:
            validate_outbound_url(self.webhook_url)
        except UnsafeUrlError as exc:
            logger.error("Webhook URL rejected (SSRF guard): %s", exc)
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    return resp.status < 400
        except Exception as e:
            logger.error("Webhook alert failed: %s", _safe_alert_error(e))
            return False
