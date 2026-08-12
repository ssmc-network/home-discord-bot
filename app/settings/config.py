from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service: str = Field(default="home-discord-bot")
    tz: str = Field(default="Asia/Tokyo")
    loglevel: str = Field(default="INFO")

    discord_token: str = Field(default="token")

    redis_host: str = Field(default="redis-service")
    redis_port: int = Field(default=6379)
    redis_max_connections: int = Field(default=10)
    discord_channel_id: int = Field(default=123456789)


settings = Settings()
