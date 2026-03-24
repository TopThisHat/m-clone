from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = ""
    redis_url: str = ""
    stale_threshold: int = 600         # seconds before job is reclaimed (must exceed max job timeout)
    reclaim_interval: int = 30         # seconds between stale scans
    listen_channel: str = "job_available"
    default_max_attempts: int = 3
    default_job_timeout: int = 300     # seconds — worker default timeout
    metrics_port: int = 9090
    knowledge_cache_ttl_hours: int = 168   # 7 days

    # These are needed by app.config.Settings which may be loaded transitively
    openai_api_key: str = ""
    tavily_api_key: str = ""
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

    def validate_thresholds(self) -> None:
        """Assert stale_threshold > default_job_timeout at startup."""
        if self.stale_threshold <= self.default_job_timeout:
            raise ValueError(
                f"stale_threshold ({self.stale_threshold}s) must exceed "
                f"default_job_timeout ({self.default_job_timeout}s) to prevent "
                f"premature reclaim of running jobs"
            )


settings = Settings()
settings.validate_thresholds()
