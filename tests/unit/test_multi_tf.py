"""Tests for the multi-timeframe analysis endpoint (PERF-REV015)."""

from __future__ import annotations

import pandas as pd
import pytest

from quantflow.web.multi_tf import MAX_MULTI_TF_SYMBOLS, MultiTfRequest


def _payload(**over: object) -> dict:
    base: dict = {"symbols": ["BTC/USDT"], "fields": "meta"}
    base.update(over)  # type: ignore[arg-type]
    return base


class TestMultiTfRequestValidation:
    def test_defaults_to_full_analysis_vocabulary(self) -> None:
        req = MultiTfRequest(_payload())
        assert len(req.timeframes) == 24
        assert req.fields == "meta"

    def test_rejects_empty_symbols(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            MultiTfRequest(_payload(symbols=[]))

    def test_rejects_symbol_overflow(self) -> None:
        with pytest.raises(ValueError, match="limited"):
            MultiTfRequest(_payload(symbols=["X/USDT"] * (MAX_MULTI_TF_SYMBOLS + 1)))

    def test_rejects_unknown_timeframes(self) -> None:
        with pytest.raises(ValueError, match="Unsupported timeframes"):
            MultiTfRequest(_payload(timeframes=["45m", "7q"]))

    def test_rejects_timeframe_overflow(self) -> None:
        with pytest.raises(ValueError, match="timeframes limited"):
            MultiTfRequest(
                _payload(timeframes=["5m"] * 30)
            )

    def test_rejects_bad_fields(self) -> None:
        with pytest.raises(ValueError, match="fields"):
            MultiTfRequest(_payload(fields="everything"))

    def test_non_dict_body_raises(self) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            MultiTfRequest(["not", "a", "dict"])  # type: ignore[arg-type]


class TestAnalyzeShape:
    def test_response_contract_on_missing_data(self, tmp_path: pd.DataFrame) -> None:
        # With no parquet data the per-TF results degrade to insufficient_data
        # markers instead of failing — partial-success semantics.
        from quantflow.data.resample import ANALYSIS_TIMEFRAMES
        from quantflow.web.multi_tf import _analyze_symbol
        from quantflow.web.service import StationService

        service = StationService()
        result = _analyze_symbol(service, "BTC/USDT", list(ANALYSIS_TIMEFRAMES), None, None, False)
        assert set(result) == {"symbol", "partial", "warnings", "timeframes"}
        for tf in result["timeframes"]:
            assert {"timeframe", "bars", "insufficient_data"} <= set(tf)
