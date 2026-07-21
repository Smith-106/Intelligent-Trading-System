"""Tests for quantflow.common.url_safety — SSRF prevention (ISS-003/SEC-010)."""

from __future__ import annotations

import pytest

from quantflow.common.url_safety import UnsafeUrlError, validate_outbound_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/hook",
        "https://alerts.example.com/inbox",
        "https://1.1.1.1/hook",  # public IP
        "https://8.8.8.8/dns",
    ],
)
def test_accepts_public_https(url: str):
    assert validate_outbound_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",  # non-https
        "ftp://example.com/hook",  # wrong scheme
        "https://127.0.0.1/hook",  # loopback
        "https://localhost/hook",  # loopback name
        "https://sub.localhost/hook",  # .localhost suffix
        "https://10.0.0.5/hook",  # private
        "https://192.168.1.1/hook",  # private
        "https://172.16.0.1/hook",  # private
        "https://169.254.169.254/meta-data",  # link-local (cloud metadata)
        "https://224.0.0.1/hook",  # multicast
        "https://0.0.0.0/hook",  # unspecified
        "https://user:pass@example.com/hook",  # userinfo creds
        "https://[::1]/hook",  # IPv6 loopback
        "",
    ],
)
def test_rejects_unsafe(url: str):
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url(url)


def test_require_https_false_allows_http():
    # When https is not required (e.g. an internal trusted sink), http is OK
    # but scheme/host checks still apply.
    assert validate_outbound_url("http://example.com/hook", require_https=False) == (
        "http://example.com/hook"
    )
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("http://127.0.0.1/hook", require_https=False)


def test_rejects_missing_host():
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("https:///path")
