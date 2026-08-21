"""Unit tests for Alert Routing Matrix and Deduplicator (ISS-20260802-005).

Tests cover:
- ALERT_ROUTING matrix resolution
- AlertDeduplicator sliding window behavior
- AlertManager.send_routed() integration
- Priority → AlertLevel inference
- Channel filtering
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from quantflow.monitoring.alerts import (
    ALERT_ROUTING,
    DEFAULT_ALERT_CHANNELS,
    AlertCategory,
    AlertDeduplicator,
    AlertLevel,
    AlertManager,
    AlertPriority,
    resolve_alert_channels,
)

# ---------------------------------------------------------------------------
# Test: ALERT_ROUTING Resolution
# ---------------------------------------------------------------------------


class TestAlertRoutingResolution:
    """Tests for resolve_alert_channels function."""

    def test_p0_emergency_routes_to_multiple_channels(self):
        """P0 emergency alerts route to telegram + webhook."""
        channels = resolve_alert_channels(
            AlertCategory.RECONCILIATION_DRIFT, AlertPriority.P0_EMERGENCY
        )
        assert "telegram" in channels
        assert "webhook" in channels

    def test_p1_high_routes_correctly(self):
        """P1 high priority orphan order routes to telegram + webhook."""
        channels = resolve_alert_channels(AlertCategory.ORPHAN_ORDER, AlertPriority.P1_HIGH)
        assert "telegram" in channels
        assert "webhook" in channels

    def test_p2_medium_routes_to_telegram(self):
        """P2 medium data staleness routes to telegram only."""
        channels = resolve_alert_channels(AlertCategory.DATA_STALENESS, AlertPriority.P2_MEDIUM)
        assert channels == ["telegram"]

    def test_p3_low_routes_to_webhook(self):
        """P3 low system health routes to webhook batch."""
        channels = resolve_alert_channels(AlertCategory.SYSTEM_HEALTH, AlertPriority.P3_LOW)
        assert channels == ["webhook"]

    def test_unknown_combination_uses_default(self):
        """Unmapped (category, priority) falls back to DEFAULT_ALERT_CHANNELS."""
        # RISK_THRESHOLD + P3_LOW is not in the matrix
        channels = resolve_alert_channels(AlertCategory.RISK_THRESHOLD, AlertPriority.P3_LOW)
        assert channels == DEFAULT_ALERT_CHANNELS

    def test_all_routing_entries_have_valid_channels(self):
        """All ALERT_ROUTING entries reference known channel names."""
        valid_channels = {"telegram", "line", "webhook", "pagerduty"}
        for key, channels in ALERT_ROUTING.items():
            for ch in channels:
                assert ch in valid_channels, f"Invalid channel '{ch}' for {key}"


# ---------------------------------------------------------------------------
# Test: AlertDeduplicator
# ---------------------------------------------------------------------------


class TestAlertDeduplicator:
    """Tests for sliding window alert deduplication."""

    def test_first_alert_always_sends(self):
        """First occurrence of an alert key is always allowed."""
        dedup = AlertDeduplicator(window_seconds=300)
        assert dedup.should_send("reconciliation_drift:BTC/USDT") is True

    def test_duplicate_within_window_suppressed(self):
        """Same alert key within window is suppressed."""
        dedup = AlertDeduplicator(window_seconds=300)

        assert dedup.should_send("key1") is True
        assert dedup.should_send("key1") is False  # Duplicate
        assert dedup.should_send("key1") is False  # Still duplicate

    def test_different_keys_independent(self):
        """Different alert keys are tracked independently."""
        dedup = AlertDeduplicator(window_seconds=300)

        assert dedup.should_send("key_a") is True
        assert dedup.should_send("key_b") is True  # Different key
        assert dedup.should_send("key_a") is False  # Dup of key_a
        assert dedup.should_send("key_b") is False  # Dup of key_b

    def test_expired_window_allows_resend(self):
        """After window expires, same key can be sent again."""
        dedup = AlertDeduplicator(window_seconds=1)  # 1 second window

        assert dedup.should_send("key1") is True
        assert dedup.should_send("key1") is False

        # Simulate time passing beyond window
        dedup._seen["key1"] = [time.time() - 2]  # 2 seconds ago

        assert dedup.should_send("key1") is True  # Window expired

    def test_suppressed_count_tracking(self):
        """suppressed_count increments for each suppressed alert."""
        dedup = AlertDeduplicator(window_seconds=300)

        assert dedup.suppressed_count == 0
        dedup.should_send("key1")  # Sent
        dedup.should_send("key1")  # Suppressed
        dedup.should_send("key1")  # Suppressed
        assert dedup.suppressed_count == 2

    def test_make_key_with_symbol(self):
        """make_key generates correct format with symbol."""
        dedup = AlertDeduplicator()
        key = dedup.make_key(AlertCategory.RECONCILIATION_DRIFT, "BTC/USDT")
        assert key == "reconciliation_drift:BTC/USDT"

    def test_make_key_without_symbol(self):
        """make_key generates category-only key when no symbol."""
        dedup = AlertDeduplicator()
        key = dedup.make_key(AlertCategory.SYSTEM_HEALTH)
        assert key == "system_health"

    def test_reset_clears_state(self):
        """reset() clears all dedup state."""
        dedup = AlertDeduplicator(window_seconds=300)

        dedup.should_send("key1")
        dedup.should_send("key1")  # Suppressed
        assert dedup.suppressed_count == 1

        dedup.reset()
        assert dedup.suppressed_count == 0
        assert dedup.should_send("key1") is True  # Can send again


# ---------------------------------------------------------------------------
# Test: AlertManager.send_routed()
# ---------------------------------------------------------------------------


class TestAlertManagerSendRouted:
    """Tests for smart routing integration in AlertManager."""

    @pytest.mark.asyncio
    async def test_send_routed_deduplicates(self):
        """send_routed suppresses duplicate alerts within window."""
        manager = AlertManager(
            telegram_token="fake-token",
            telegram_chat_id="123",
            dedup_window_seconds=300,
        )

        with patch.object(manager, "_send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = True

            # First send goes through
            result1 = await manager.send_routed(
                message="Drift detected",
                category=AlertCategory.RECONCILIATION_DRIFT,
                priority=AlertPriority.P0_EMERGENCY,
                symbol="BTC/USDT",
            )
            assert "telegram" in result1
            mock_tg.assert_awaited_once()

            # Second identical alert is suppressed
            result2 = await manager.send_routed(
                message="Drift detected",
                category=AlertCategory.RECONCILIATION_DRIFT,
                priority=AlertPriority.P0_EMERGENCY,
                symbol="BTC/USDT",
            )
            assert result2 == {}  # Empty = suppressed

    @pytest.mark.asyncio
    async def test_send_routed_infers_level_from_priority(self):
        """send_routed infers AlertLevel from AlertPriority."""
        manager = AlertManager(
            telegram_token="fake-token",
            telegram_chat_id="123",
        )

        with patch.object(manager, "_send_telegram", new_callable=AsyncMock) as mock_tg:
            mock_tg.return_value = True

            await manager.send_routed(
                message="Emergency!",
                category=AlertCategory.DRAWDOWN_BREACH,
                priority=AlertPriority.P0_EMERGENCY,
            )

            # P0 → CRITICAL level
            call_args = mock_tg.call_args
            assert call_args[0][1] == AlertLevel.CRITICAL

    @pytest.mark.asyncio
    async def test_send_routed_filters_channels(self):
        """send_routed only sends to channels in routing matrix."""
        manager = AlertManager(
            telegram_token="fake-token",
            telegram_chat_id="123",
            line_token="line-token",
            line_user_id="line-user",
            webhook_url="https://example.com/hook",
        )

        with (
            patch.object(manager, "_send_telegram", new_callable=AsyncMock) as mock_tg,
            patch.object(manager, "_send_line", new_callable=AsyncMock) as mock_line,
            patch.object(manager, "_send_webhook", new_callable=AsyncMock) as mock_wh,
        ):
            mock_tg.return_value = True
            mock_line.return_value = True
            mock_wh.return_value = True

            # DATA_STALENESS + P2 → only telegram
            await manager.send_routed(
                message="Data stale",
                category=AlertCategory.DATA_STALENESS,
                priority=AlertPriority.P2_MEDIUM,
            )

            mock_tg.assert_awaited_once()
            mock_line.assert_not_awaited()
            mock_wh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deduplicator_accessible(self):
        """AlertManager exposes deduplicator for metrics."""
        manager = AlertManager(dedup_window_seconds=60)
        assert manager.deduplicator is not None
        assert manager.deduplicator.suppressed_count == 0
