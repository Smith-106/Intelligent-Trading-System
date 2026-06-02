"""Tests for alert delivery paths."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import pytest

from quantflow.monitoring.alerts import AlertLevel, AlertManager


class _FakeResponse:
    def __init__(self, status: int):
        self.status = status

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeSession:
    def __init__(self, status: int):
        self.status = status
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse(self.status)


class _FailingSession:
    async def __aenter__(self) -> _FailingSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url: str, **kwargs: object) -> _FakeResponse:
        raise RuntimeError("network down")


@pytest.mark.asyncio
async def test_send_dispatches_to_configured_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = AlertManager(
        telegram_token="tg-token",
        telegram_chat_id="chat-id",
        line_token="line-token",
        line_user_id="user-id",
        webhook_url="https://example.com/hook",
    )

    async def fake_telegram(message: str, level: AlertLevel, extra: dict[str, object] | None) -> bool:
        assert message == "hello"
        assert level is AlertLevel.CRITICAL
        assert extra == {"k": "v"}
        return True

    async def fake_line(message: str, level: AlertLevel) -> bool:
        assert message == "hello"
        assert level is AlertLevel.CRITICAL
        return False

    async def fake_webhook(message: str, level: AlertLevel, extra: dict[str, object] | None) -> bool:
        assert message == "hello"
        assert level is AlertLevel.CRITICAL
        assert extra == {"k": "v"}
        return True

    monkeypatch.setattr(manager, "_send_telegram", fake_telegram)
    monkeypatch.setattr(manager, "_send_line", fake_line)
    monkeypatch.setattr(manager, "_send_webhook", fake_webhook)

    result = await manager.send("hello", AlertLevel.CRITICAL, extra={"k": "v"})

    assert result == {"telegram": True, "line": False, "webhook": True}


@pytest.mark.asyncio
async def test_send_telegram_success_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = AlertManager(telegram_token="tg-token", telegram_chat_id="chat-id")
    session = _FakeSession(status=200)
    monkeypatch.setattr("quantflow.monitoring.alerts.aiohttp.ClientSession", lambda: session)

    ok = await manager._send_telegram("hello", AlertLevel.WARNING, {"symbol": "BTC/USDT"})

    assert ok is True
    call = cast(dict[str, Any], session.calls[0])
    payload = cast(dict[str, Any], call["json"])
    assert call["url"] == "https://api.telegram.org/bottg-token/sendMessage"
    assert payload["chat_id"] == "chat-id"
    assert "[WARNING] hello" in payload["text"]
    assert '"symbol": "BTC/USDT"' in payload["text"]


@pytest.mark.asyncio
async def test_send_line_success_builds_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = AlertManager(line_token="line-token", line_user_id="user-id")
    session = _FakeSession(status=200)
    monkeypatch.setattr("quantflow.monitoring.alerts.aiohttp.ClientSession", lambda: session)

    ok = await manager._send_line("line-message", AlertLevel.INFO)

    assert ok is True
    call = cast(dict[str, Any], session.calls[0])
    headers = cast(dict[str, Any], call["headers"])
    payload = cast(dict[str, Any], call["json"])
    messages = cast(list[dict[str, Any]], payload["messages"])
    assert headers["Authorization"] == "Bearer line-token"
    assert payload["to"] == "user-id"
    assert messages[0]["text"] == "[INFO] line-message"


@pytest.mark.asyncio
async def test_send_webhook_accepts_any_2xx_or_3xx(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = AlertManager(webhook_url="https://example.com/hook")
    session = _FakeSession(status=302)
    monkeypatch.setattr("quantflow.monitoring.alerts.aiohttp.ClientSession", lambda: session)

    ok = await manager._send_webhook("hook-message", AlertLevel.CRITICAL, {"code": 7})

    assert ok is True
    call = cast(dict[str, Any], session.calls[0])
    assert call["url"] == "https://example.com/hook"
    assert call["json"] == {
        "level": "critical",
        "message": "hook-message",
        "code": 7,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sender_name", "args"),
    [
        ("_send_telegram", ("hello", AlertLevel.INFO, None)),
        ("_send_line", ("hello", AlertLevel.INFO)),
        ("_send_webhook", ("hello", AlertLevel.INFO, None)),
    ],
)
async def test_alert_senders_return_false_on_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    sender_name: str,
    args: tuple[object, ...],
) -> None:
    manager = AlertManager(
        telegram_token="tg-token",
        telegram_chat_id="chat-id",
        line_token="line-token",
        line_user_id="user-id",
        webhook_url="https://example.com/hook",
    )
    monkeypatch.setattr("quantflow.monitoring.alerts.aiohttp.ClientSession", lambda: _FailingSession())

    sender: Callable[..., object] = getattr(manager, sender_name)
    result = await sender(*args)

    assert result is False
