"""
AWS Secrets Manager helper for Postgres and ElastiCache credentials.

Postgres secret shape:
    { "host": "...", "port": 5432, "username": "...", "password": "...", "dbname": "..." }

ElastiCache secret shape:
    { "url": "rediss://host:port", "auth_token": "..." }
  or:
    { "host": "...", "port": 6379, "auth_token": "..." }

Secrets are cached in process memory.  Call the matching invalidate_*() function
to evict the cache so the next fetch re-pulls from AWS — called automatically
when a rotation error is detected at runtime.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


def _fetch_secret(secret_name: str, region: str) -> dict:
    import boto3  # lazy — only needed in cloud environments
    client = boto3.client("secretsmanager", region_name=region)
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])


# ── Postgres ──────────────────────────────────────────────────────────────────

_cached_db_secret: dict | None = None


def get_db_secret(secret_name: str, region: str) -> dict:
    """Return cached Postgres secret, fetching from Secrets Manager if needed."""
    global _cached_db_secret
    if _cached_db_secret is None:
        logger.info("Fetching DB secret %r from Secrets Manager (%s)", secret_name, region)
        _cached_db_secret = _fetch_secret(secret_name, region)
    return _cached_db_secret


def invalidate_db_secret() -> None:
    """Evict cached Postgres secret so the next get_db_secret() re-fetches from AWS."""
    global _cached_db_secret
    _cached_db_secret = None
    logger.info("DB secret cache cleared — will re-fetch on next pool creation")


def build_dsn(secret: dict) -> str:
    """
    Build a postgresql:// DSN from secret fields.
    The password is percent-encoded so special characters don't break the URL.
    """
    host = secret["host"]
    port = secret.get("port", 5432)
    username = secret["username"]
    password = quote_plus(str(secret["password"]))
    dbname = secret["dbname"]
    return f"postgresql://{username}:{password}@{host}:{port}/{dbname}"


# ── ElastiCache / Redis ───────────────────────────────────────────────────────

_cached_redis_secret: dict | None = None


def get_redis_secret(secret_name: str, region: str) -> dict:
    """Return cached Redis secret, fetching from Secrets Manager if needed."""
    global _cached_redis_secret
    if _cached_redis_secret is None:
        logger.info("Fetching Redis secret %r from Secrets Manager (%s)", secret_name, region)
        _cached_redis_secret = _fetch_secret(secret_name, region)
    return _cached_redis_secret


def invalidate_redis_secret() -> None:
    """Evict cached Redis secret so the next get_redis_secret() re-fetches from AWS."""
    global _cached_redis_secret
    _cached_redis_secret = None
    logger.info("Redis secret cache cleared — will re-fetch on next client creation")


def build_redis_url(secret: dict) -> tuple[str, str | None]:
    """
    Return (url, auth_token) from secret fields.

    Accepts either:
      { "url": "rediss://host:port", "auth_token": "..." }
      { "host": "...", "port": 6379,  "auth_token": "..." }

    The returned URL always uses the rediss:// (TLS) scheme.
    auth_token is None if the secret doesn't include one.
    """
    token: str | None = secret.get("auth_token") or secret.get("token") or None
    if "url" in secret:
        url = secret["url"]
        # Normalise plain redis:// → rediss:// for ElastiCache in-transit encryption
        if url.startswith("redis://"):
            url = "rediss://" + url[len("redis://"):]
        return url, token
    host = secret["host"]
    port = secret.get("port", 6379)
    return f"rediss://{host}:{port}", token


# ── Azure OpenAI (PEM + config) ─────────────────────────────────────────────

_cached_azure_pem: str | None = None


def get_azure_pem_secret(secret_name: str, region: str) -> str:
    """Return cached Azure PEM certificate, fetching from Secrets Manager if needed."""
    global _cached_azure_pem
    if _cached_azure_pem is None:
        logger.info("Fetching Azure PEM secret %r from Secrets Manager (%s)", secret_name, region)
        raw = _fetch_secret(secret_name, region)
        # The secret may store the PEM as a single string field or as {"pem": "..."}
        _cached_azure_pem = raw.get("pem", raw) if isinstance(raw, dict) else str(raw)
    return _cached_azure_pem


def invalidate_azure_pem_secret() -> None:
    global _cached_azure_pem
    _cached_azure_pem = None
    logger.info("Azure PEM secret cache cleared")


_cached_azure_config: dict | None = None


def get_azure_config_secret(secret_name: str, region: str) -> dict:
    """Return cached Azure config JSON: {endpoint, client_id, tenant_id, api_key}."""
    global _cached_azure_config
    if _cached_azure_config is None:
        logger.info("Fetching Azure config secret %r from Secrets Manager (%s)", secret_name, region)
        _cached_azure_config = _fetch_secret(secret_name, region)
    return _cached_azure_config


def invalidate_azure_config_secret() -> None:
    global _cached_azure_config
    _cached_azure_config = None
    logger.info("Azure config secret cache cleared")
