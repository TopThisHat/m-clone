from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    openai_api_key: str
    tavily_api_key: str
    database_url: str = ""
    allowed_origins: list[str] = ["http://localhost:5173"]
    max_pdf_size_mb: int = 20
    max_upload_size_mb: int | None = None
    redis_url: str = ""
    redis_ttl_hours: int = 24

    # AI models
    anthropic_api_key: str = ""
    default_model: str = "openai:gpt-4o"

    # AWS Secrets Manager (set in dev/uat/prod instead of DATABASE_URL / REDIS_URL)
    aws_secret_name: str = ""              # e.g. "prod/myapp/db"
    aws_elasticache_secret_name: str = ""  # e.g. "prod/myapp/redis"
    aws_region: str = "us-east-1"

    # Azure OpenAI via AWS Secrets Manager
    aws_mode: bool = False
    aws_azure_pem_secret: str = ""
    aws_azure_config_secret: str = ""
    env_name: str = "local"
    cloud_proxy_host: str = ""
    cloud_proxy_port: int = 11111
    cloud_proxy_cert: str = "cert/uat.cert"

    # Auth / SSO
    oidc_issuer: str = ""
    oidc_client_id: str = "m-clone"
    oidc_client_secret: str = ""
    jwt_secret: str = "change-me-in-prod"
    dev_auth_bypass: bool = False
    app_base_url: str = "http://localhost:5173"

    @model_validator(mode="after")
    def _sync_upload_size(self) -> "Settings":
        if self.max_upload_size_mb is not None:
            self.max_pdf_size_mb = self.max_upload_size_mb
        else:
            self.max_upload_size_mb = self.max_pdf_size_mb
        return self

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"


settings = Settings()
