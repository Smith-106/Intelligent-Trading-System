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
    if not tail:  # spot / perpetual
        return f"{base}{quote}".upper()
    # Delivery: unified expiry token '260904' (YYMMDD) -> native '04SEP26'.
    expiry = tail.partition("-")[2]
    if len(expiry) != 6 or not expiry.isdigit():
        raise DataError(f"Invalid Bybit delivery symbol (bad expiry): {symbol!r}")
    yy, mm, dd = expiry[:2], expiry[2:4], expiry[4:]
    native_expiry = f"{dd}{_MONTH_ABBR[int(mm) - 1]}{yy}"
    return f"{base}{quote}-{native_expiry}".upper()


def bybit_store_symbol(symbol: str, *, suffix: str = "-BYBIT") -> str:
    """Storage key for a Bybit symbol, validator-safe.

    Perpetual/spot keeps the unified form: ``BTC/USDT`` -> ``BTC/USDT-BYBIT``
    (dir ``BTC_USDT-BYBIT``, unchanged from P2 behaviour).
    Delivery maps to the native id: ``BTC/USDT:USDT-260904`` ->
    ``BTCUSDT260904-BYBIT`` (19 chars — the ``:`` is validator-illegal).
    Falls back to the bare market id when the suffixed form would exceed the
    20-char validator cap.
    """
    if ":" not in symbol:
        store = f"{symbol}{suffix}"
        if len(store) <= STORE_SYMBOL_MAX_LEN:
            return store
        return bybit_market_id(symbol)
    mid = bybit_market_id(symbol)
    store = f"{mid}{suffix}"
    if len(store) <= STORE_SYMBOL_MAX_LEN:
        return store
    return mid
