"""Cross-cutting input validation primitives.

Security-sensitive validators shared across the data and web layers live here
(public API) so callers depend on a stable contract rather than borrowing
private helpers from sibling modules. Centralizing these also gives a single
choke point to audit when the validation rules change.

Why public (no underscore): these are deliberately shared. A leading underscore
would mark them as module-private implementation details, which is the wrong
contract for a security primitive imported across layers.
"""

from __future__ import annotations

import math
import re

# Trading-pair symbols: alphanumerics plus / _ -, max 20 chars. The / is the
# CCXT pair separator (e.g. "BTC/USDT"); it is replaced with _ when used as a
# filesystem/SQL identifier. Quotes, backslashes, dots, and glob metacharacters
# are rejected, which is what closes the SQL-injection / path-traversal surface.
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9/_-]{1,20}$")

# SQL column names: identifier-first char + alnum/underscore. Used to validate
# dynamically composed SELECT lists before interpolation.
COLUMN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Absolute magnitude below which a position is treated as flat. Centralized
# (previously 1e-10 was inlined across 4 files) so the "what counts as zero"
# policy has one source of truth. See odyssey-improve(trade-main-path) §5.
POSITION_EPSILON = 1e-10


def validate_symbol(symbol: str) -> str:
    """Validate a trading-pair symbol and return its filesystem/SQL-safe form.

    Returns the symbol with ``/`` replaced by ``_`` (the on-disk partition
    directory name). Raises ``ValueError`` if the symbol contains characters
    outside ``[A-Za-z0-9/_-]`` or exceeds 20 characters.

    This is the single validation choke point for every code path that turns a
    user/operator-supplied symbol into a DuckDB glob or a Parquet path —
    closing the SEC-001 SQL-injection and the path-traversal surfaces.
    """
    if not SYMBOL_PATTERN.match(symbol):
        raise ValueError(
            f"Invalid symbol format: {symbol!r}. "
            "Only alphanumeric, /, _, - characters allowed (max 20 chars)."
        )
    return symbol.replace("/", "_")


def validate_columns(columns: list[str] | tuple[str, ...] | None) -> list[str] | None:
    """Validate SQL column names and return a deduplicated list (or None)."""
    if columns is None:
        return None
    if not columns:
        raise ValueError("columns must not be empty")
    invalid = [column for column in columns if not COLUMN_PATTERN.match(column)]
    if invalid:
        raise ValueError(f"Invalid column name(s): {invalid!r}")
    return list(dict.fromkeys(columns))


def validate_quantity(quantity: float) -> float:
    """Validate an order/position quantity before it reaches the exchange.

    Rejects NaN, +/-inf, zero, and negative values. NaN/inf previously slipped
    through the live order path (okx_gateway used an opaque ``x == x`` NaN
    trick that did not catch +inf), and close-position orders built from
    exchange-reported positions inherited whatever ``float(p.get('contracts'))``
    returned — including non-finite values from a malformed response. This is
    the symmetric choke point to ``validate_symbol``: every Order construction
    on the live path (send_order, close_position, KillSwitch) MUST pass its
    quantity through here.

    Returns the quantity unchanged on success.
    """
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError(f"Invalid quantity (must be finite and > 0): {quantity!r}")
    return quantity
