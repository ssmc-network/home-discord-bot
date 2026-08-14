import redis

from settings.config import settings


class RedisConnector:
    def __init__(
        self,
        host: str = settings.redis_host,
        port: int = settings.redis_port,
        max_connections: int = settings.redis_max_connections,
    ) -> None:
        """初期化"""
        self.host = host
        self.port = port
        self.max_connections = max_connections
        self._pool: redis.ConnectionPool | None = None

    def get_connection(self) -> redis.Redis:
        # ConnectionPoolの生成はソケット接続を伴わない(実際の接続は最初のコマンド発行時に
        # 遅延で行われる)ため、ここでの接続エラーハンドリングは意味を持たない。
        # 接続エラーは実際にコマンドを実行する呼び出し元(main.py)で捕捉すること。
        if self._pool is None:
            self._pool = redis.ConnectionPool(
                host=self.host,
                port=self.port,
                max_connections=self.max_connections,
                decode_responses=True,
            )
        return redis.Redis(connection_pool=self._pool)
