"""REV-010 security round regression tests (three-model consensus audit).

Covers the fixes landed after the consensus security audit (SEC-1..SEC-6):
- SEC-1: web entry installs the log-redaction safety net (setup_logging)
- SEC-3: reconciler/redis logs no longer carry raw exception bodies / redis
  password URLs
- SEC-4: hardening response headers on every web response
- SEC-5: SessionStartRequest.symbol validated at the web boundary
- SEC-6: rdagent subprocess receives a whitelist env, not the full process env
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from aiohttp.test_utils import make_mocked_request
from typer.testing import CliRunner

from quantflow.web.security import _SECURITY_HEADERS, security_headers_guard

runner = CliRunner()


# --- SEC-1 ---------------------------------------------------------------
def test_run_station_installs_setup_logging(monkeypatch) -> None:
    calls: list[str] = []

    def fake_setup_logging(**kwargs) -> None:
        calls.append(kwargs.get("level", ""))

    import quantflow.web.app as app_mod

    monkeypatch.setattr("quantflow.monitoring.logger.setup_logging", fake_setup_logging)
    with patch.object(app_mod, "web") as fake_web:
        fake_web.run_app = lambda *a, **k: None
        app_mod.run_station(host="127.0.0.1", port=18088)
    assert calls, "setup_logging must be called from run_station"
    assert calls[0] == "INFO"


# --- SEC-3 ---------------------------------------------------------------
def test_redis_log_uses_safe_endpoint(monkeypatch) -> None:
    from quantflow.data.redis_cache import RedisCache

    cache = RedisCache(url="redis://:s3cr3t@127.0.0.1:6379")
    safe = cache._safe_redis_endpoint("redis://:s3cr3t@127.0.0.1:6379/0")
    assert "s3cr3t" not in safe
    assert safe == "redis://127.0.0.1:6379"


def test_reconciler_logs_are_redacted() -> None:
    from quantflow.reconciliation import engine as reconciler

    with open(reconciler.__file__, encoding="utf-8") as fh:
        src = fh.read()
    # every exception-log line must route through redact_secrets
    for line in src.splitlines():
        if "logger.error" in line or "logger.warning" in line:
            if "%s" in line and "redact_secrets" not in line:
                # %s that is NOT an exception object is fine (ids/counts);
                # flag any %s whose arg is a bare exception name
                assert "redact_secrets" in line or ", e)" not in line, line


# --- SEC-4 ---------------------------------------------------------------
@pytest.mark.asyncio
async def test_security_headers_applied() -> None:
    request = make_mocked_request("GET", "/api/overview")

    async def handler(req):
        from aiohttp import web

        return web.json_response({})

    resp = await security_headers_guard(request, handler)
    for key in _SECURITY_HEADERS:
        assert resp.headers.get(key) == _SECURITY_HEADERS[key], key


def test_security_headers_values() -> None:
    assert _SECURITY_HEADERS["X-Content-Type-Options"] == "nosniff"
    assert _SECURITY_HEADERS["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in _SECURITY_HEADERS["Content-Security-Policy"]


# --- SEC-5 ---------------------------------------------------------------
def test_session_start_symbol_validation() -> None:
    from pydantic import ValidationError

    from quantflow.web.session_manager import SessionStartRequest

    good = SessionStartRequest(symbol="BTC/USDT")
    # validate_symbol normalises the separator to the storage form.
    assert good.symbol == "BTC_USDT"
    with pytest.raises(ValidationError):
        SessionStartRequest(symbol="../../etc/passwd")


# --- SEC-6 ---------------------------------------------------------------
def test_rdagent_subprocess_env_is_whitelisted() -> None:
    """Structural: the rdagent subprocess env is a whitelist, never
    ``os.environ.copy()`` (OKX keys / alert tokens must not leak to the
    third-party CLI)."""
    import quantflow.strategy.rd_agent as rd_mod

    with open(rd_mod.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert "os.environ.copy()" not in src
    assert '"PATH"' in src  # whitelist keeps PATH
    assert 'env = {' in src  # whitelist block exists


