from unittest.mock import MagicMock, patch

import redis

from modules.redis_module import RedisConnector


class TestRedisConnector:
    def test_get_connection_builds_pool_from_configured_params(self) -> None:
        connector = RedisConnector(host="redis-host", port=6380, max_connections=5)

        with patch("modules.redis_module.redis.ConnectionPool") as mock_pool_cls:
            mock_pool_cls.return_value = MagicMock()
            conn = connector.get_connection()

        mock_pool_cls.assert_called_once_with(
            host="redis-host",
            port=6380,
            max_connections=5,
            decode_responses=True,
        )
        assert isinstance(conn, redis.Redis)

    def test_connection_pool_is_created_only_once(self) -> None:
        connector = RedisConnector()

        with patch("modules.redis_module.redis.ConnectionPool") as mock_pool_cls:
            mock_pool_cls.return_value = MagicMock()
            connector.get_connection()
            connector.get_connection()

        mock_pool_cls.assert_called_once()
