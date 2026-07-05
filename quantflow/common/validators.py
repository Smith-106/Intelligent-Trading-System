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

import re

# Trading-pair symbols: alphanumerics plus / _ -, max 20 chars. The / is the
# CCXT pair separator (e.g. "BTC/USDT"); it is replaced with _ when used as a
# filesystem/SQL identifier. Quotes, backslashes, dots, and glob metacharacters
# are rejected, which is what closes the SQL-injection / path-traversal surface.
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9/_-]{1,20}$")

# SQL column names: identifier-first char + alnum/underscore. Used to validate
# dynamically composed SELECT lists before interpolation.
COLUMN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
