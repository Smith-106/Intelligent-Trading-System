"""Alert manager with Telegram and LINE notification support."""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class AlertLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertManager:
    """Manage alerts with Telegram/LINE/webhook notifications.

    Configure via environment variables or config:
    - TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
    - LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID
    - WEBHOOK_URL (generic webhook)
    """

    def __init__(
        self,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        line_token: str = "",
        line_user_id: str = "",
        webhook_url: str = "",
    ):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.line_token = line_token
        self.line_user_id = line_user_id
        self.webhook_url = webhook_url

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

    async def _send_telegram(
        self, message: str, level: AlertLevel, extra: dict | None,
    ) -> bool:
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        text = f"[{level.value.upper()}] {message}"
        if extra:
            text += f"\n{json.dumps(extra, default=str)}"
        payload = {"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "HTML"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error("Telegram alert failed: %s", e)
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
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error("LINE alert failed: %s", e)
            return False

    async def _send_webhook(
        self, message: str, level: AlertLevel, extra: dict | None,
    ) -> bool:
        payload = {"level": level.value, "message": message, **(extra or {})}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    return resp.status < 400
        except Exception as e:
            logger.error("Webhook alert failed: %s", e)
            return False
