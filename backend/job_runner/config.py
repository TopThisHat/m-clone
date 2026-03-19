from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    redis_url: str = ""
    stale_threshold: int = 120         # seconds before job is reclaimed
    reclaim_interval: int = 30         # seconds between stale scans
    listen_channel: str = "job_available"
    default_max_attempts: int = 3
    metrics_port: int = 9090
    knowledge_cache_ttl_hours: int = 168   # 7 days

    # These are needed by app.config.Settings which may be loaded transitively
    openai_api_key: str = ""
    tavily_api_key: str = ""
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
