from __future__ import annotations

import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator, model_validator

logger = logging.getLogger(__name__)

# RFC-1918, loopback, link-local, and other internal ranges that must not
# be reachable via a user-supplied webhook URL (SSRF prevention).
_BLOCKED_NETWORKS = [
    ipaddress.ip_network(cidr) for cidr in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "::1/128",
        "fc00::/7",
        "169.254.0.0/16",   # link-local
        "100.64.0.0/10",    # shared address space
        "0.0.0.0/8",
        "240.0.0.0/4",
    )
]


def _is_internal_ip(hostname: str) -> bool:
    """Return True if hostname resolves to an internal/blocked IP range."""
    try:
        addr = ipaddress.ip_address(hostname)
        return any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        # Not a bare IP — hostname will be resolved at request time, which we
        # cannot fully prevent, but we block known internal hostnames.
        lower = hostname.lower()
        return lower in ("localhost", "metadata.google.internal") or lower.endswith(".internal")


class AsyncResearchRequest(BaseModel):
    query: str
    webhook_url: str
    doc_session_key: str | None = None
    team_id: str | None = None

    @field_validator("webhook_url")
    @classmethod
    def _validate_webhook_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme != "https":
            raise ValueError("webhook_url must use HTTPS")
        hostname = parsed.hostname or ""
        if not hostname:
            raise ValueError("webhook_url must have a valid hostname")
        if _is_internal_ip(hostname):
            raise ValueError("webhook_url must not target internal or private IP addresses")
        return v

    @model_validator(mode="before")
    @classmethod
    def _migrate_pdf_session_key(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        old = data.pop("pdf_session_key", None)
        if old is not None:
            logger.warning("pdf_session_key is deprecated, use doc_session_key")
            if data.get("doc_session_key") is None:
                data["doc_session_key"] = old
        return data


class JobStatus(BaseModel):
    job_id: str
    status: str  # queued | running | done | failed
    created_at: str
    result_markdown: str = ""
    error: str | None = None
