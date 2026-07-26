"""Tests for redis_cache module — using mock to avoid Redis dependency."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from quantflow.common.exceptions import DataError
from quantflow.data.redis_cache import RedisCache


class TestRedisCache:
    """Test RedisCache with mocked Redis connection."""

    def test_init_default(self):
        cache = RedisCache()
        assert cache._url == "redis://localhost:6379"
        assert cache._db == 0
        assert cache._client is None

    def test_init_custom(self):
        cache = RedisCache(url="redis://custom:6380", db=1)
        assert cache._url == "redis://custom:6380"
        assert cache._db == 1

    @patch("quantflow.data.redis_cache.redis")
    def test_connect_success(self, mock_redis_module):
        mock_client = MagicMock()
        mock_redis_module.from_url.return_value = mock_client

        cache = RedisCache()
        cache.connect()

        assert cache._client is mock_client
        mock_client.ping.assert_called_once()

    @patch("quantflow.data.redis_cache.redis")
    def test_connect_failure(self, mock_redis_module):
        mock_redis_module.from_url.side_effect = Exception("Connection refused")

        cache = RedisCache()
        cache.connect()

        assert cache._client is None

    def test_set_ticker_no_connection(self):
        cache = RedisCache()
        cache._client = None
        cache.set_ticker("BTC/USDT", {"price": 50000})  # Should not raise

    def test_get_ticker_no_connection(self):
        """ISS-20260723-015: client=None is a connection-state failure,
        not a cache miss — must raise DataError so callers don't silently
        bypass the cache forever after a connection drop."""
        cache = RedisCache()
        cache._client = None
        with pytest.raises(DataError, match="not connected"):
            cache.get_ticker("BTC/USDT")

    def test_set_latest_bar_no_connection(self):
        cache = RedisCache()
        cache._client = None
        cache.set_latest_bar("BTC/USDT", "1h", {"close": 50000})  # Should not raise

    def test_get_latest_bar_no_connection(self):
        """ISS-20260723-015: see test_get_ticker_no_connection — raises DataError."""
        cache = RedisCache()
        cache._client = None
        with pytest.raises(DataError, match="not connected"):
            cache.get_latest_bar("BTC/USDT", "1h")

    @patch("quantflow.data.redis_cache.redis")
    def test_set_and_get_ticker(self, mock_redis_module):
        mock_client = MagicMock()
        mock_redis_module.from_url.return_value = mock_client

        cache = RedisCache()
        cache.connect()

        cache.set_ticker("BTC/USDT", {"price": 50000, "volume": 1000})
        mock_client.setex.assert_called_once()
        call_args = mock_client.setex.call_args
        assert call_args[0][0] == "ticker:BTC/USDT"

    @patch("quantflow.data.redis_cache.redis")
    def test_get_ticker_with_data(self, mock_redis_module):
        import json

        mock_client = MagicMock()
        mock_redis_module.from_url.return_value = mock_client
        mock_client.get.return_value = json.dumps({"price": 50000})

        cache = RedisCache()
        cache.connect()

        result = cache.get_ticker("BTC/USDT")
        assert result == {"price": 50000}

    @patch("quantflow.data.redis_cache.redis")
    def test_get_ticker_key_miss_returns_none(self, mock_redis_module):
        """ISS-20260723-015 guard: a genuine key miss (raw falsy) still
        returns None — only client=None raises. Prevents the antipattern
        from regressing (caller must distinguish miss from failure)."""
        mock_client = MagicMock()
        mock_redis_module.from_url.return_value = mock_client
        mock_client.get.return_value = None  # key miss

        cache = RedisCache()
        cache.connect()

        result = cache.get_ticker("BTC/USDT")
        assert result is None

    @patch("quantflow.data.redis_cache.redis")
    def test_get_latest_bar_key_miss_returns_none(self, mock_redis_module):
        """ISS-20260723-015 guard: key miss on latest_bar still returns None."""
        mock_client = MagicMock()
        mock_redis_module.from_url.return_value = mock_client
        mock_client.get.return_value = None

        cache = RedisCache()
        cache.connect()

        result = cache.get_latest_bar("BTC/USDT", "1h")
        assert result is None

    def test_disconnect(self):
        cache = RedisCache()
        cache._client = MagicMock()
        cache.disconnect()
        assert cache._client is None

    def test_disconnect_no_connection(self):
        cache = RedisCache()
        cache._client = None
        cache.disconnect()  # Should not raise
