from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    max_concurrency: int = 50
    heartbeat_interval: int = 30       # seconds between heartbeats
    stale_threshold: int = 120         # seconds before job is reclaimed
    reclaim_interval: int = 30         # seconds between stale scans
    listen_channel: str = "job_available"
    default_max_attempts: int = 3
    default_backoff_base: float = 4.0  # seconds (doubles per attempt + jitter)
    openai_api_key: str = ""
    tavily_api_key: str = ""
    anthropic_api_key: str = ""
    per_type_limits: dict[str, int] = {}   # e.g. {"validation_pair": 10}
    default_job_timeout: int = 300         # seconds
    type_timeouts: dict[str, int] = {}     # e.g. {"validation_pair": 600}
    metrics_port: int = 9090
    knowledge_cache_ttl_hours: int = 168   # 7 days

    class Config:
        env_file = ".env"


settings = Settings()
