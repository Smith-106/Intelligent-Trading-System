"""Tests for ISS-008 (SEC-021/022): session security.

- session_id uses secrets.token_urlsafe (high entropy, not enumerable) instead
  of uuid4().hex[:6] (24 bits).
- operator_id is recorded for audit: from QUANTFLOW_OPERATOR_ID, or a stable
  short hash of the Station token (token itself never stored), or None in
  loopback no-token mode.
"""

from __future__ import annotations

from quantflow.web.session_manager import StationSessionManager


def test_session_id_has_high_entropy_and_is_unique():
    """ISS-022: generated session ids are not enumerable and are unique."""
    ids = {StationSessionManager._build_session_id() for _ in range(200)}
    # 200 unique ids (no collisions from a 24-bit space would collide here).
    assert len(ids) == 200
    for sid in ids:
        # Format: station-YYYYMMDD-HHMMSS-<token>. token_urlsafe may itself
        # contain '-', so split on exactly the first 3 dashes.
        parts = sid.split("-", 3)
        assert len(parts) == 4
        assert parts[0] == "station"
        token = parts[3]
        # token_urlsafe(16) yields ~22 chars; well beyond the old 6-hex (24-bit).
        assert len(token) >= 16


def test_session_id_suffix_not_short_hex():
    """The old format was uuid4().hex[:6] = exactly 6 hex chars. The new token
    part (after station-date-time-) must be materially longer."""
    sid = StationSessionManager._build_session_id()
    token = sid.split("-", 3)[3]
    assert not (len(token) == 6 and all(c in "0123456789abcdef" for c in token))


def test_operator_id_from_explicit_env(monkeypatch):
    monkeypatch.setenv("QUANTFLOW_OPERATOR_ID", "alice-ops")
    monkeypatch.delenv("QUANTFLOW_STATION_TOKEN", raising=False)
    assert StationSessionManager._operator_id() == "alice-ops"


def test_operator_id_from_token_hash(monkeypatch):
    """When no explicit operator id, derive a stable short hash of the token.
    The token itself is never stored — only an 8-char SHA-256 prefix."""
    monkeypatch.delenv("QUANTFLOW_OPERATOR_ID", raising=False)
    monkeypatch.setenv("QUANTFLOW_STATION_TOKEN", "a-strong-secret-token-xyz")
    op = StationSessionManager._operator_id()
    assert op is not None
    assert op.startswith("token:")
    # Stable across calls (same token → same id).
    assert StationSessionManager._operator_id() == op
    # The raw token is NOT present in the operator id.
    assert "a-strong-secret-token-xyz" not in op


def test_operator_id_none_without_token_or_env(monkeypatch):
    monkeypatch.delenv("QUANTFLOW_OPERATOR_ID", raising=False)
    monkeypatch.delenv("QUANTFLOW_STATION_TOKEN", raising=False)
    assert StationSessionManager._operator_id() is None


def test_operator_id_truncates_long_explicit_env(monkeypatch):
    monkeypatch.setenv("QUANTFLOW_OPERATOR_ID", "x" * 200)
    monkeypatch.delenv("QUANTFLOW_STATION_TOKEN", raising=False)
    assert len(StationSessionManager._operator_id()) <= 64


def test_empty_snapshot_exposes_operator_id_none():
    """The empty (no-session) snapshot carries operator_id: None for schema
    consistency with the live snapshot (ISS-021)."""
    snap = StationSessionManager()._empty_snapshot()
    assert "operator_id" in snap
    assert snap["operator_id"] is None
