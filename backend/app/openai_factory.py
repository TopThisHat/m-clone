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

    # Determine proxy settings — scoped to Azure token + OpenAI client ONLY.
    # We intentionally do NOT set os.environ["HTTPS_PROXY"] globally, because
    # that would route tool HTTP calls (Tavily, Wikipedia, SEC EDGAR, Yahoo
    # Finance) through the corporate proxy unnecessarily.
    proxy_url: str | None = None
    proxy_cert: str | None = None
    if settings.env_name in ("dev", "uat", "prod") and settings.cloud_proxy_host:
        proxy_url = f"http://{settings.cloud_proxy_host}:{settings.cloud_proxy_port}"
        proxy_cert = settings.cloud_proxy_cert
        logger.info("Azure proxy configured: %s (cert: %s)", proxy_url, proxy_cert)

    credential = CertificateCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        certificate_path=pem_path,
    )

    # Custom auth that injects the Azure AD bearer token on each request.
    # Proxy env vars are set ONLY during the synchronous get_token() call
    # (MSAL/requests needs them) and immediately restored afterwards.
    class _AzureBearerAuth(httpx.Auth):
        def __init__(
            self,
            cred: CertificateCredential,
            _proxy_url: str | None,
            _proxy_cert: str | None,
        ) -> None:
            self._cred = cred
            self._proxy_url = _proxy_url
            self._proxy_cert = _proxy_cert

        def auth_flow(self, request: httpx.Request):
            old_proxy = os.environ.get("HTTPS_PROXY")
            old_cert = os.environ.get("REQUESTS_CA_BUNDLE")
            try:
                if self._proxy_url:
                    os.environ["HTTPS_PROXY"] = self._proxy_url
                if self._proxy_cert:
                    os.environ["REQUESTS_CA_BUNDLE"] = self._proxy_cert
                token = self._cred.get_token(
                    "https://cognitiveservices.azure.com/.default"
                )
            finally:
                # Restore original env — keep proxy out of tool HTTP calls
                if old_proxy is not None:
                    os.environ["HTTPS_PROXY"] = old_proxy
                else:
                    os.environ.pop("HTTPS_PROXY", None)
                if old_cert is not None:
                    os.environ["REQUESTS_CA_BUNDLE"] = old_cert
                else:
                    os.environ.pop("REQUESTS_CA_BUNDLE", None)
            request.headers["Authorization"] = f"Bearer {token.token}"
            yield request

    # Build httpx client with proxy scoped to OpenAI API calls only
    http_kwargs: dict = {
        "auth": _AzureBearerAuth(credential, proxy_url, proxy_cert),
        "timeout": 120,
    }
    if proxy_url:
        http_kwargs["proxy"] = proxy_url
    if proxy_cert:
        http_kwargs["verify"] = proxy_cert

    http_client = httpx.AsyncClient(**http_kwargs)

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
