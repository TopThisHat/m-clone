"""
Central factory for all OpenAI client creation.

- aws_mode=False  →  standard AsyncOpenAI with settings.openai_api_key
- aws_mode=True   →  Azure OpenAI via cert-based token + corporate proxy
"""
from __future__ import annotations

import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import certifi
import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

_CERT_EXTENSIONS = {".cert", ".crt", ".pem"}


def _build_combined_ca_bundle(cert_dir: Path) -> str:
    """Build a CA bundle combining system CAs (certifi) with proxy certs.

    Returns the path to a temp file containing the combined bundle,
    or certifi.where() if cert_dir doesn't exist or has no cert files.
    """
    if not cert_dir.is_dir():
        return certifi.where()

    extra_certs: list[Path] = [
        p for p in sorted(cert_dir.iterdir())
        if p.is_file() and p.suffix in _CERT_EXTENSIONS
    ]
    if not extra_certs:
        return certifi.where()

    tmp = tempfile.NamedTemporaryFile(
        suffix=".pem", delete=False, mode="w", encoding="utf-8",
    )
    # Start with the full system CA bundle
    tmp.write(Path(certifi.where()).read_text(encoding="utf-8"))
    # Append each proxy / corporate cert
    for cert_path in extra_certs:
        tmp.write("\n")
        tmp.write(cert_path.read_text(encoding="utf-8"))
    tmp.flush()
    bundle_path = tmp.name
    tmp.close()
    logger.info(
        "Combined CA bundle: %s (%d extra certs from %s)",
        bundle_path, len(extra_certs), cert_dir,
    )
    return bundle_path


@contextmanager
def _proxy_env(proxy_url: str | None, ca_bundle: str | None):
    """Temporarily set HTTPS_PROXY and REQUESTS_CA_BUNDLE, restoring on exit.

    No-ops when proxy_url is None.
    """
    if proxy_url is None:
        yield
        return

    old_proxy = os.environ.get("HTTPS_PROXY")
    old_cert = os.environ.get("REQUESTS_CA_BUNDLE")
    try:
        os.environ["HTTPS_PROXY"] = proxy_url
        if ca_bundle:
            os.environ["REQUESTS_CA_BUNDLE"] = ca_bundle
        yield
    finally:
        if old_proxy is not None:
            os.environ["HTTPS_PROXY"] = old_proxy
        else:
            os.environ.pop("HTTPS_PROXY", None)
        if old_cert is not None:
            os.environ["REQUESTS_CA_BUNDLE"] = old_cert
        else:
            os.environ.pop("REQUESTS_CA_BUNDLE", None)


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
        # Build combined CA bundle: system CAs + proxy certs from cert directory
        cert_dir = Path(settings.cloud_proxy_cert).parent
        proxy_cert = _build_combined_ca_bundle(cert_dir)
        logger.info("Azure proxy configured: %s (ca_bundle: %s)", proxy_url, proxy_cert)

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
            with _proxy_env(self._proxy_url, self._proxy_cert):
                token = self._cred.get_token(
                    "https://cognitiveservices.azure.com/.default"
                )
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
