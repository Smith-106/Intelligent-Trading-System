"""Cross-cutting secret redaction.

Centralizes the scrubbing of secret values from strings that may be persisted
to snapshots/history or surfaced to clients (exception messages, error logs,
telemetry). Keeping this in ``common/`` (public, not a private helper in a
sibling module) follows the G2 coding standard: a security choke point shared
across layers is public API with a single audit surface.

Why public (no underscore): secret redaction is referenced by the web layer
(session_manager snapshots, app error handlers) and could be reused by the
monitoring/execution layers. A private ``_redact`` borrowed via cross-module
import would be the wrong contract (see quantflow-review-antipatterns:
"private-security-primitive borrow-in").
"""

from __future__ import annotations

import os
import re

# Environment variables whose values, if present in a string, must be redacted.
# Order is irrelevant — we scan for each value's literal occurrence. Keep this
# list as the single source of truth for "what counts as a secret" so a new
# integration (e.g. a future alert channel) only adds its env name here.
SECRET_ENV_NAMES: tuple[str, ...] = (
    # OKX exchange credentials
    "OKX_API_KEY",
    "OKX_SECRET",
    "OKX_PASSPHRASE",
    # QuantFlow Station web auth token
    "QUANTFLOW_STATION_TOKEN",
    # Alert channel tokens — Telegram URLs embed the bot token
    # (https://api.telegram.org/bot{token}/sendMessage) and connection errors
    # echoing the URL would otherwise persist it to last_error → snapshots.
    "TELEGRAM_BOT_TOKEN",
    "LINE_CHANNEL_ACCESS_TOKEN",
    # Infrastructure credentials
    "REDIS_PASSWORD",
    "GRAFANA_ADMIN_PASSWORD",
)

# Bot-token-shaped regexes: match the Telegram bot token format
# "{digits}:{base64url-ish 30+ chars}" even when the env var is not set (so a
# token that leaked into a string from any source — config file, URL, error
# body — is still scrubbed). Telegram URLs embed the token directly after the
# literal "bot" prefix (https://api.telegram.org/bot{token}/sendMessage); a
# word boundary (\b) does not fire at "t6", so the "bot"-anchored pattern
# catches URL-embedded tokens, and a non-word lookbehind catches bare tokens.
_BOT_TOKEN_AFTER_PREFIX = re.compile(r"(?<=bot)(\d{6,}:[A-Za-z0-9_-]{30,})")
_BOT_TOKEN_BARE = re.compile(r"(?<![\w])(\d{6,}:[A-Za-z0-9_-]{30,})")

# Bearer-token-shaped regex: scrub Authorization header values that may end up
# in proxied/echoed error text. Matches "Bearer <token>" (RFC 6750).
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+=/]{20,}")

# redis://user:password@host URL credential portion.
_REDIS_URL_PASSWORD_PATTERN = re.compile(r"(redis://[^:/@]+:)[^@/]+(@)")

REDACTED_PLACEHOLDER = "***REDACTED***"


def redact_secrets(text: str) -> str:
    """Redact known secret values and secret-shaped substrings from ``text``.

    Two layers:
    1. Literal env values: any environment variable listed in
       :data:`SECRET_ENV_NAMES` whose value appears verbatim in ``text`` is
       replaced with ``***REDACTED***``.
    2. Shape-based patterns: bot tokens, Bearer headers, and redis-URL
       passwords are scrubbed even when their source env is unset (covers
       tokens that leaked from a config file or an error body).

    Returns the scrubbed string. Empty/None input is returned unchanged.
    """
    if not text:
        return text
    redacted = text
    for env_name in SECRET_ENV_NAMES:
        value = os.environ.get(env_name)
        if value and value in redacted:
            redacted = redacted.replace(value, REDACTED_PLACEHOLDER)
    redacted = _BOT_TOKEN_AFTER_PREFIX.sub(REDACTED_PLACEHOLDER, redacted)
    redacted = _BOT_TOKEN_BARE.sub(REDACTED_PLACEHOLDER, redacted)
    redacted = _BEARER_PATTERN.sub("Bearer " + REDACTED_PLACEHOLDER, redacted)
    redacted = _REDIS_URL_PASSWORD_PATTERN.sub(r"\1" + REDACTED_PLACEHOLDER + r"\2", redacted)
    return redacted
