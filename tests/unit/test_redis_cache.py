"""Tests for redis_cache module — using mock to avoid Redis dependency."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
        cache = RedisCache()
        cache._client = None
        result = cache.get_ticker("BTC/USDT")
        assert result is None

    def test_set_latest_bar_no_connection(self):
        cache = RedisCache()
        cache._client = None
        cache.set_latest_bar("BTC/USDT", "1h", {"close": 50000})  # Should not raise

    def test_get_latest_bar_no_connection(self):
        cache = RedisCache()
        cache._client = None
        result = cache.get_latest_bar("BTC/USDT", "1h")
        assert result is None

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

    def test_disconnect(self):
        cache = RedisCache()
        cache._client = MagicMock()
        cache.disconnect()
        assert cache._client is None

    def test_disconnect_no_connection(self):
        cache = RedisCache()
        cache._client = None
        cache.disconnect()  # Should not raise
