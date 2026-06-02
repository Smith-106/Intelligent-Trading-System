"""Focused tests for remaining small module coverage gaps."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pandas as pd
import pytest

from quantflow.common.models import Order, Position
from quantflow.data.feature_store import FeatureStore
from quantflow.data.redis_cache import RedisCache
from quantflow.execution.gateway_base import GatewayBase
from quantflow.indicators.base import FactorBase, FactorRegistry, registry
from quantflow.indicators.momentum import rsi, stochastic, stochastic_rsi, williams_r
from quantflow.indicators.volatility import (
    atr,
    bollinger_bands,
    donchian_channel,
    keltner_channel,
    true_range,
)


class _EchoFactor(FactorBase):
    name = "echo_factor"

    def compute(self, df: pd.DataFrame, **params: object) -> pd.Series:
        multiplier = int(cast(int, params.get("multiplier", 1)))
        return df["close"] * multiplier


class _DummyGateway(GatewayBase):
    async def connect(self, config: dict[str, object] | None = None) -> None:
        self.config = config

    async def send_order(self, order: Order) -> str:
        return "dummy-order"

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        return True

    async def query_positions(self) -> list[Position]:
        return []


def _price_series(length: int = 30) -> tuple[pd.Series, pd.Series, pd.Series]:
    close = pd.Series([100.0 + idx for idx in range(length)], dtype=float)
    high = close + 2.0
    low = close - 2.0
    return high, low, close


class TestFactorRegistrySmallGaps:
    def test_compute_raises_for_missing_factor_and_global_registry_is_registry(self) -> None:
        local_registry = FactorRegistry()

        with pytest.raises(KeyError, match="Factor not registered: missing_factor"):
            local_registry.compute("missing_factor", pd.DataFrame({"close": [1.0]}))

        assert isinstance(registry, FactorRegistry)

    def test_list_factors_returns_sorted_names(self) -> None:
        local_registry = FactorRegistry()

        class BFactor(FactorBase):
            name = "b_factor"

            def compute(self, df: pd.DataFrame, **params: object) -> pd.Series:
                return df["close"]

        class AFactor(FactorBase):
            name = "a_factor"

            def compute(self, df: pd.DataFrame, **params: object) -> pd.Series:
                return df["close"]

        local_registry.register(BFactor)
        local_registry.register(AFactor)

        assert local_registry.list_factors() == ["a_factor", "b_factor"]


class TestGatewayBaseDefaults:
    @pytest.mark.asyncio
    async def test_default_optional_methods_are_safe_noops(self) -> None:
        gateway = _DummyGateway()

        assert await gateway.cancel_all_orders() == []
        await gateway.disconnect()
        await gateway.subscribe("ticker", callback=AsyncMock())


class TestMomentumIndicators:
    def test_rsi_handles_flat_series_without_exceeding_bounds(self) -> None:
        flat = pd.Series([100.0] * 20, dtype=float)

        result = rsi(flat, period=5)

        assert len(result) == len(flat)
        assert result.dropna().between(0, 100).all()

    def test_stochastic_rsi_handles_zero_range_and_returns_expected_columns(self) -> None:
        flat = pd.Series([100.0] * 30, dtype=float)

        result = stochastic_rsi(flat, rsi_period=5, stoch_period=5, k_smooth=2, d_smooth=2)

        assert list(result.columns) == ["stochrsi_k", "stochrsi_d"]
        assert result["stochrsi_k"].dropna().eq(0).all()

    def test_stochastic_and_williams_r_handle_flat_range(self) -> None:
        flat = pd.Series([50.0] * 20, dtype=float)

        stoch = stochastic(flat, flat, flat, k_period=5, d_period=2)
        wr = williams_r(flat, flat, flat, period=5)

        assert list(stoch.columns) == ["stoch_k", "stoch_d"]
        assert stoch["stoch_k"].dropna().eq(0).all()
        assert wr.dropna().eq(0).all()


class TestVolatilityIndicators:
    def test_true_range_and_atr_compute_expected_values(self) -> None:
        high, low, close = _price_series(6)

        tr = true_range(high, low, close)
        atr_result = atr(high, low, close, period=3)

        assert tr.iloc[0] == pytest.approx(4.0)
        assert tr.iloc[1] == pytest.approx(4.0)
        assert atr_result.iloc[2] == pytest.approx(4.0)

    def test_band_indicators_return_expected_shapes(self) -> None:
        high, low, close = _price_series(25)

        bb = bollinger_bands(close, period=5, std_dev=2.0)
        kc = keltner_channel(high, low, close, ema_period=5, atr_period=3, multiplier=1.5)
        dc = donchian_channel(high, low, period=5)

        assert list(bb.columns) == ["bb_upper", "bb_middle", "bb_lower"]
        assert list(kc.columns) == ["kc_upper", "kc_middle", "kc_lower"]
        assert list(dc.columns) == ["dc_upper", "dc_middle", "dc_lower"]
        assert len(bb) == len(close)
        assert len(kc) == len(close)
        assert len(dc) == len(close)


class TestFeatureStoreSmallGaps:
    def test_compute_features_appends_symbol_and_timestamp(self, tmp_path: pytest.TempPathFactory) -> None:
        store = FeatureStore(str(tmp_path))
        raw = pd.DataFrame(
            {
                "timestamp": [1, 2, 3],
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [10.0, 20.0, 30.0],
            }
        )
        raw_store = Mock()
        raw_store.query.return_value = raw
        computed = pd.DataFrame({"timestamp": [1, 2, 3], "feature_a": [0.1, 0.2, 0.3]})

        with patch("quantflow.indicators.engine.IndicatorEngine.compute_all", return_value=computed.copy()) as mock_compute:
            result = store.compute_features("BTC/USDT", 3, ["feature_a"], raw_store)

        mock_compute.assert_called_once()
        assert "symbol" in result.columns
        assert "computed_at" in result.columns
        assert result["symbol"].eq("BTC/USDT").all()
        assert result["computed_at"].eq(3).all()


class TestRedisCacheSmallGaps:
    def test_set_and_get_latest_bar_with_connection(self) -> None:
        cache = RedisCache()
        cache._client = MagicMock()
        cache._client.get.return_value = '{"close": 123.4}'

        cache.set_latest_bar("BTC/USDT", "1h", {"close": 123.4})
        result = cache.get_latest_bar("BTC/USDT", "1h")

        cache._client.setex.assert_called_once()
        args = cache._client.setex.call_args.args
        assert args[0] == "bar:BTC/USDT:1h"
        assert args[1] == 300
        assert result == {"close": 123.4}
