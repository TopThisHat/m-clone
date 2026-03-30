"""
Worker configuration.

Workers consume from Redis Streams and execute workflow logic.
Scale independently by deploying multiple worker instances.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings

from app.streams import (
    STREAM_VALIDATION_CAMPAIGN,
    STREAM_VALIDATION_CLUSTER,
    STREAM_VALIDATION_PAIR,
)

# All available workflow streams
ALL_WORKFLOW_STREAMS = [
    STREAM_VALIDATION_CAMPAIGN,
    STREAM_VALIDATION_PAIR,
    STREAM_VALIDATION_CLUSTER,
]


class Settings(BaseSettings):
    database_url: str = ""
    redis_url: str = ""
    openai_api_key: str = ""
    tavily_api_key: str = ""
    anthropic_api_key: str = ""

    # Which streams to consume (comma-separated or "all")
    # e.g. "jobs:validation_pair" or "jobs:validation_campaign,jobs:validation_pair"
    worker_streams: str = "all"

    # Max concurrent jobs per stream
    worker_concurrency: int = 20

    # Heartbeat interval in seconds
    heartbeat_interval: int = 30

    # Default backoff base for retries (seconds, doubles per attempt + jitter)
    default_backoff_base: float = 4.0

    # Default job timeout in seconds
    default_job_timeout: int = 300

    # Per-type timeout overrides e.g. {"validation_pair": 600}
    type_timeouts: dict[str, int] = {}

    # Per-type concurrency limits e.g. {"validation_pair": 10}
    per_type_limits: dict[str, int] = {}

    # Consumer group name
    consumer_group: str = "workers"

    # Knowledge cache TTL
    knowledge_cache_ttl_hours: int = 168  # 7 days

    # Max attempts before dead-letter
    default_max_attempts: int = 3

    # Run entity extraction consumer
    enable_extraction: bool = True

    # Health check HTTP server port (0 to disable)
    worker_health_port: int = 9091

    class Config:
        env_file = ".env"
        extra = "ignore"

    def get_streams(self) -> list[str]:
        """Return list of streams this worker should consume."""
        if self.worker_streams == "all":
            return ALL_WORKFLOW_STREAMS
        return [s.strip() for s in self.worker_streams.split(",") if s.strip()]


settings = Settings()
