from pathlib import Path

from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    openai_api_key: str
    tavily_api_key: str
    database_url: str = ""
    allowed_origins: list[str] = ["http://localhost:5173"]
    max_pdf_size_mb: int = 20
    redis_url: str = ""
    redis_ttl_hours: int = 24

    # AI models
    anthropic_api_key: str = ""
    default_model: str = "openai:gpt-4o"

    # Auth / SSO
    oidc_issuer: str = ""
    oidc_client_id: str = "m-clone"
    oidc_client_secret: str = ""
    jwt_secret: str = "change-me-in-prod"
    dev_auth_bypass: bool = False
    app_base_url: str = "http://localhost:5173"

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"


settings = Settings()
