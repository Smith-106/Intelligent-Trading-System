"""Cross-cutting URL safety validation (SSRF prevention).

ISS-003 (SEC-010): a generic webhook / outbound-HTTP sink that POSTs to an
operator-configurable URL is an SSRF sink unless the URL is confined to a safe
scheme and host. This module centralizes the allowlist so AlertManager (and
any future outbound-HTTP caller) validates through one choke point — the G2
coding standard: a security primitive shared across layers is public API in
``quantflow/common/``.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    """Raised when a URL fails the SSRF / scheme safety check."""


def validate_outbound_url(url: str, *, require_https: bool = True) -> str:
    """Validate an outbound HTTP target URL for SSRF safety.

    Rules:
    - Scheme MUST be ``https`` when ``require_https`` is True (loopback
      plaintext is the Station's own contract, not a webhook's).
    - Host MUST resolve to a non-loopback, non-private, non-link-local,
      non-multicast, non-unspecified address. Literal-IP hosts are checked
      directly; hostname hosts are accepted (DNS resolution is deferred to the
      HTTP client, which is acceptable for the single-operator threat model —
      the guard rejects the obvious foot-guns: ``127.0.0.1``, ``localhost``,
      ``10.x``/``192.168.x``, link-local ``169.254.x``, metadata endpoints).
    - ``localhost`` and the loopback names are rejected explicitly.
    - No userinfo (``user:pass@host``) — webhook URLs should not embed creds.

    Returns the URL on success (so the call site can chain). Raises
    :class:`UnsafeUrlError` on any failure.
    """
    if not url:
        raise UnsafeUrlError("outbound URL is empty")
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise UnsafeUrlError(f"unparseable URL: {exc}") from exc

    scheme = (parsed.scheme or "").lower()
    if require_https and scheme != "https":
        raise UnsafeUrlError(
            f"outbound URL must use https (got {scheme!r}); loopback/plain-http "
            "targets are not permitted for webhooks"
        )
    if not require_https and scheme not in ("http", "https"):
        raise UnsafeUrlError(f"outbound URL must be http(s) (got {scheme!r})")

    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeUrlError("outbound URL has no host")

    # Reject userinfo — webhook URLs must not embed credentials.
    if parsed.username or parsed.password:
        raise UnsafeUrlError("outbound URL must not embed userinfo credentials")

    # Reject obvious loopback names before any IP parse.
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        raise UnsafeUrlError("loopback host is not permitted for outbound HTTP")

    # Literal-IP hosts: reject any non-public address.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname — accepted; DNS resolved by the HTTP client. The hostname
        # allowlist (public DNS) is the operator's responsibility.
        return url
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        raise UnsafeUrlError(
            f"non-public IP {ip} is not permitted for outbound HTTP "
            "(loopback/private/link-local/multicast/unspecified/reserved rejected)"
        )
    return url
