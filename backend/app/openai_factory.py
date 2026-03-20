"""
Central factory for all OpenAI client creation.

- aws_mode=False  →  standard AsyncOpenAI with settings.openai_api_key
- aws_mode=True   →  Azure OpenAI via cert-based token + corporate proxy
"""
from __future__ import annotations

import logging
import os
import tempfile

import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _build_standard_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.openai_api_key)


def _build_azure_client() -> AsyncOpenAI:
    from azure.identity import CertificateCredential

    from app.secrets import get_azure_config_secret, get_azure_pem_secret

    pem_data = get_azure_pem_secret(settings.aws_azure_pem_secret, settings.aws_region)
    config = get_azure_config_secret(settings.aws_azure_config_secret, settings.aws_region)

    endpoint = config["endpoint"]
    client_id = config["client_id"]
    tenant_id = config["tenant_id"]
    api_key = config["api_key"]

    # Write PEM to a temp file for CertificateCredential
    tmp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    tmp.write(pem_data.encode() if isinstance(pem_data, str) else pem_data)
    tmp.flush()
    pem_path = tmp.name
    tmp.close()

    # Set proxy env vars for dev/uat/prod environments
    if settings.env_name in ("dev", "uat", "prod") and settings.cloud_proxy_host:
        proxy_url = f"http://{settings.cloud_proxy_host}:{settings.cloud_proxy_port}"
        os.environ["HTTPS_PROXY"] = proxy_url
        os.environ["REQUESTS_CA_BUNDLE"] = settings.cloud_proxy_cert
        logger.info("Azure proxy configured: %s (cert: %s)", proxy_url, settings.cloud_proxy_cert)

    credential = CertificateCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        certificate_path=pem_path,
    )

    # Custom auth that injects the Azure AD bearer token on each request
    class _AzureBearerAuth(httpx.Auth):
        def __init__(self, cred: CertificateCredential) -> None:
            self._cred = cred

        def auth_flow(self, request: httpx.Request):
            token = self._cred.get_token("https://cognitiveservices.azure.com/.default")
            request.headers["Authorization"] = f"Bearer {token.token}"
            yield request

    http_client = httpx.AsyncClient(auth=_AzureBearerAuth(credential), timeout=120)

    return AsyncOpenAI(
        base_url=endpoint,
        api_key=api_key,
        http_client=http_client,
    )


def get_openai_client() -> AsyncOpenAI:
    """Return cached singleton OpenAI client."""
    global _client
    if _client is None:
        if settings.aws_mode:
            _client = _build_azure_client()
            logger.info("OpenAI client: Azure mode (endpoint from Secrets Manager)")
        else:
            _client = _build_standard_client()
            logger.info("OpenAI client: standard mode (api_key)")
    return _client


def initialize() -> None:
    """Eagerly create the client at startup (useful for aws_mode to fail fast)."""
    get_openai_client()
