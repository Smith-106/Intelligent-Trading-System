"""IMP-REV013-2: pure-function coverage for the previously zero-tested
Bybit/Binance data-layer helpers.

bybit_common.py and binance_fetcher.py had no test references at all (the
only mentions were help-text assertions in the CLI golden test), despite
containing hand-rolled symbol/epoch parsing that already shipped one silent
bug (RV-007-008/M4 negative-index DEC month). These are pure functions —
zero mocking required.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantflow.common.exceptions import DataError
from quantflow.data.binance_fetcher import _normalize_epoch_ms, _to_binance_symbol
from quantflow.data.bybit_common import (
    STORE_SYMBOL_MAX_LEN,
    bybit_market_id,
    bybit_store_symbol,
)


class TestBybitMarketId:
    def test_spot_maps_to_concatenated_upper(self) -> None:
        assert bybit_market_id("BTC/USDT") == "BTCUSDT"
        assert bybit_market_id("eth/usdt") == "ETHUSDT"

    def test_perpetual_ignores_settlement_currency(self) -> None:
        # IMP-REV013 bugfix: perps ("BTC/USDT:USDT") previously fell into the
        # delivery parser and raised on the empty expiry, rejecting the
        # documented download path for every Bybit linear contract.
        assert bybit_market_id("BTC/USDT:USDT") == "BTCUSDT"
        # store form drops the ':' via the native id (validator-illegal char).
        assert bybit_store_symbol("BTC/USDT:USDT") == "BTCUSDT-BYBIT"

    def test_delivery_maps_expiry_to_native_form(self) -> None:
        # unified YYMMDD -> native DDMMMYY (verified against ccxt 2026-08)
        assert bybit_market_id("BTC/USDT:USDT-260904") == "BTCUSDT-04SEP26"
        assert bybit_market_id("BTC/USDT:USDT-270131") == "BTCUSDT-31JAN27"

    @pytest.mark.parametrize(
        ("bad", "why"),
        [
            ("BTCUSDT", "no separator"),
            ("BTC/USDT:USDT-2609", "expiry too short"),
            ("BTC/USDT:USDT-2609041", "expiry too long"),
            ("BTC/USDT:USDT-BAD", "expiry not digits"),
            # RV-007-008/M4 regression: month '00' hit the negative index and
            # silently mapped to DEC. Expiry is YYMMDD, so mm=00 -> "260004".
            ("BTC/USDT:USDT-260004", "month 00"),
            ("BTC/USDT:USDT-261304", "month 13"),
            ("BTC/USDT:USDT-260900", "day 00"),
            ("BTC/USDT:USDT-260932", "day 32"),
        ],
    )
    def test_invalid_symbols_raise_data_error(self, bad: str, why: str) -> None:
        with pytest.raises(DataError):
            bybit_market_id(bad)


class TestBybitStoreSymbol:
    def test_perpetual_gets_suffix(self) -> None:
        assert bybit_store_symbol("BTC/USDT") == "BTC/USDT-BYBIT"

    def test_delivery_drops_colon(self) -> None:
        # The native id already carries a dash (BTCUSDT-04SEP26), so appending
        # -BYBIT would exceed the validator cap — the bare id is stored.
        store = bybit_store_symbol("BTC/USDT:USDT-260904")
        assert ":" not in store
        assert store == "BTCUSDT-04SEP26"

    def test_over_validator_cap_raises(self) -> None:
        # IMP-REV013: a symbol whose bare native id still exceeds the cap is
        # refused explicitly — the old fallback silently emitted an invalid
        # storage key.
        long_base = "X" * STORE_SYMBOL_MAX_LEN
        with pytest.raises(DataError):
            bybit_store_symbol(f"{long_base}/USDT")


class TestNormalizeEpochMs:
    def test_millisecond_stamps_pass_through(self) -> None:
        ms = np.array([1_700_000_000_000, 1_600_000_000_000], dtype="int64")
        result = _normalize_epoch_ms(ms)
        assert list(result) == list(ms)

    def test_microsecond_stamps_are_divided(self) -> None:
        us = np.array([1_700_000_000_000_000, 1_600_000_000_000_000], dtype="int64")
        result = _normalize_epoch_ms(us)
        assert list(result) == [1_700_000_000_000, 1_600_000_000_000]

    def test_mixed_series(self) -> None:
        v = pd.Series([1_700_000_000_000, 1_700_000_000_000_000], dtype="int64")
        result = _normalize_epoch_ms(v)
        assert list(result) == [1_700_000_000_000, 1_700_000_000_000]


class TestToBinanceSymbol:
    def test_unified_symbol_strips_quote_slash(self) -> None:
        assert _to_binance_symbol("BTC/USDT") == "BTCUSDT"
