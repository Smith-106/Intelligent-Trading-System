"""Shared Bybit symbol-mapping helpers (kline CLI + meta fetcher).

The symbol validator (``SYMBOL_PATTERN``) rejects ``:`` and caps length at 20,
so CCXT delivery symbols like ``BTC/USDT:USDT-260904`` cannot be stored as-is.
Consensus (three-model P3 review 2026-08-21, deepseek proposal adopted):
map deterministically to the native V5 market id and keep the ``-BYBIT``
suffix — the expiry date token inside the id already distinguishes delivery
from perpetual contracts, so no extra ``-FUTURES`` suffix is needed and the
validator stays untouched.
"""

from __future__ import annotations

from quantflow.common.exceptions import DataError

#: Storage-symbol hard cap from ``SYMBOL_PATTERN`` ({1,20}).
STORE_SYMBOL_MAX_LEN = 20

#: Month abbreviations used in Bybit's native delivery ids (``28AUG26``).
_MONTH_ABBR = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


def bybit_market_id(symbol: str) -> str:
    """Map a CCXT unified symbol to the native V5 market id.

    ``BTC/USDT`` -> ``BTCUSDT``; ``BTC/USDT:USDT-260904`` ->
    ``BTCUSDT-04SEP26`` (Bybit names deliveries ``<BASE><QUOTE>-<DDMMMYY>``;
    verified against ccxt markets 2026-08-21). Pure text parsing on purpose:
    Bybit's ``load_markets`` is best-effort in this codebase and may fail, so
    ``exchange.market()`` cannot be relied on.
    """
    base, sep, rest = symbol.partition("/")
    if not sep:
        raise DataError(f"Invalid Bybit symbol: {symbol!r}")
    quote, _, tail = rest.partition(":")
    if not tail or "-" not in tail:
        # IMP-REV013-bugfix: linear perps arrive as "BTC/USDT:USDT" (settle
        # currency, no delivery date). Previously only the bare spot form hit
        # this branch — a perp symbol fell into the delivery parser and died
        # on the empty expiry, rejecting the documented download path for
        # every Bybit linear contract. Spot and perp share the same native
        # V5 market id.
        return f"{base}{quote}".upper()
    # Delivery: unified expiry token '260904' (YYMMDD) -> native '04SEP26'.
    expiry = tail.partition("-")[2]
    if len(expiry) != 6 or not expiry.isdigit():
        raise DataError(f"Invalid Bybit delivery symbol (bad expiry): {symbol!r}")
    yy, mm, dd = expiry[:2], expiry[2:4], expiry[4:]
    # RV-007-008/M4: '00' month hit the negative index and silently mapped to
    # DEC; '13'+ raised a bare IndexError. Validate before indexing.
    if not 1 <= int(mm) <= 12 or not 1 <= int(dd) <= 31:
        raise DataError(f"Invalid Bybit delivery symbol (bad expiry): {symbol!r}")
    native_expiry = f"{dd}{_MONTH_ABBR[int(mm) - 1]}{yy}"
    return f"{base}{quote}-{native_expiry}".upper()


def bybit_store_symbol(symbol: str, *, suffix: str = "-BYBIT") -> str:
    """Storage key for a Bybit symbol, validator-safe.

    Perpetual/spot keeps the unified form: ``BTC/USDT`` -> ``BTC/USDT-BYBIT``
    (dir ``BTC_USDT-BYBIT``, unchanged from P2 behaviour).
    Delivery maps to the native id; because that id already carries a dash
    (``BTCUSDT-04SEP26``, 15 chars), appending ``-BYBIT`` would exceed the
    20-char validator cap, so the bare market id is returned (the ``:``
    never survives into storage either way).
    """
    mid = bybit_market_id(symbol)
    # Prefer the suffixed unified form, fall back to the bare native id; if
    # even the id exceeds the validator cap the symbol simply cannot be
    # stored safely — raise instead of silently emitting an invalid key
    # (IMP-REV013: the old fallback returned over-cap ids verbatim).
    for candidate in (f"{symbol}{suffix}", mid) if ":" not in symbol else (f"{mid}{suffix}", mid):
        if len(candidate) <= STORE_SYMBOL_MAX_LEN:
            return candidate
    raise DataError(
        f"Bybit store symbol exceeds {STORE_SYMBOL_MAX_LEN}-char cap: {symbol!r}"
    )
