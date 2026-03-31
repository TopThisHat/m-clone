"""
Redis Streams helpers for job dispatch and entity extraction.

Streams:
  - jobs:validation_campaign  — campaign fan-out jobs
  - jobs:validation_pair      — per-pair research/scoring jobs
  - entity_extraction         — KG extraction (legacy name, kept for compat)

The job_runner publishes to job dispatch streams; workers consume via
consumer groups for horizontal scaling.
"""
from __future__ import annotations

import json
import logging
import socket
from typing import Any

from redis.exceptions import RedisError

from app.redis_client import close_redis, get_redis  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stream & group constants
# ---------------------------------------------------------------------------
STREAM_VALIDATION_CAMPAIGN = "jobs:validation_campaign"
STREAM_VALIDATION_PAIR = "jobs:validation_pair"
STREAM_VALIDATION_CLUSTER = "jobs:validation_cluster"
STREAM_ENTITY_EXTRACTION = "entity_extraction"

GROUP_WORKERS = "workers"
GROUP_EXTRACTORS = "extractor"

# Map job_type → stream name for dispatch
JOB_TYPE_TO_STREAM = {
    "validation_campaign": STREAM_VALIDATION_CAMPAIGN,
    "validation_pair": STREAM_VALIDATION_PAIR,
    "validation_cluster": STREAM_VALIDATION_CLUSTER,
}


# ---------------------------------------------------------------------------
# Generic stream operations
# ---------------------------------------------------------------------------

async def create_consumer_group(stream: str, group: str) -> None:
    """Create a consumer group idempotently (ignores BUSYGROUP).

    Uses id="0" so that any messages published before the group was created
    are still delivered to consumers (id="$" would silently skip them).
    """
    try:
        r = await get_redis()
        await r.xgroup_create(stream, group, id="0", mkstream=True)
        logger.info("Created consumer group '%s' on stream '%s'", group, stream)
    except RedisError as exc:
        if "BUSYGROUP" in str(exc):
            logger.debug("Consumer group '%s' already exists on '%s'", group, stream)
        else:
            logger.warning("xgroup_create failed for %s/%s: %s", stream, group, exc)


async def publish_job(stream: str, job_data: dict[str, Any]) -> str:
    """
    Publish a job to a Redis Stream. Returns the message ID.
    job_data values are serialised to strings (Redis requirement).
    """
    from app.job_queue import _sanitize_payload

    r = await get_redis()
    # Flatten to string values for Redis
    fields = {}
    for k, v in job_data.items():
        if v is None:
            continue
        if isinstance(v, (dict, list)):
            fields[k] = json.dumps(_sanitize_payload(v) if isinstance(v, dict) else v)
        else:
            fields[k] = str(v)
    msg_id = await r.xadd(stream, fields)
    return msg_id


async def consume_jobs(
    stream: str,
    group: str,
    consumer: str,
    count: int = 1,
    block_ms: int = 5000,
) -> list[tuple[str, dict[str, str]]]:
    """
    Read up to `count` messages from the stream via consumer group.
    Returns list of (msg_id, field_dict) tuples, or empty list on timeout.
    """
    r = await get_redis()
    results = await r.xreadgroup(
        group, consumer, {stream: ">"}, count=count, block=block_ms,
    )
    if not results:
        return []
    _stream_name, messages = results[0]
    return messages


async def ack_job(stream: str, group: str, msg_id: str) -> None:
    """Acknowledge a processed message in the consumer group."""
    try:
        r = await get_redis()
        await r.xack(stream, group, msg_id)
    except RedisError as exc:
        logger.warning("xack failed for %s/%s msg=%s: %s", stream, group, msg_id, exc)


# ---------------------------------------------------------------------------
# Entity extraction helpers (backward-compatible with old app/queue.py)
# ---------------------------------------------------------------------------

_EXTRACTION_CONSUMER = f"extractor-{socket.gethostname()}"


async def publish_for_extraction(
    session_id: str,
    report_md: str,
    *,
    team_id: str | None = None,
    is_document: bool = False,
    enable_client_lookup: bool = False,
) -> None:
    """Publish a report to the entity_extraction Redis stream.

    Args:
        session_id: Unique identifier for this extraction task.
        report_md: Text content to extract entities from.
        team_id: Optional team scope for extracted entities.
        is_document: True when text came from an uploaded file (enables
            document-aware extraction prompt and batched page processing).
        enable_client_lookup: When True, the worker will also run a GWM
            client ID lookup for every extracted person entity.  Defaults
            to False so automatic KG enrichment (e.g. from research reports
            or document uploads) does not trigger expensive client lookups
            unless the user explicitly requests matching.
    """
    if not report_md or not report_md.strip():
        return
    try:
        r = await get_redis()
        fields: dict[str, str] = {
            "session_id": session_id,
            "report_md": report_md,
        }
        if team_id:
            fields["team_id"] = team_id
        if is_document:
            fields["is_document"] = "true"
        if enable_client_lookup:
            fields["enable_client_lookup"] = "true"
        await r.xadd(STREAM_ENTITY_EXTRACTION, fields, maxlen=1000, approximate=True)
        logger.debug("Published extraction task for session_id=%s", session_id)
    except RedisError as exc:
        logger.warning("Failed to publish extraction task for session_id=%s: %s", session_id, exc)


async def create_extraction_group() -> None:
    """Create the extractor consumer group (idempotent)."""
    await create_consumer_group(STREAM_ENTITY_EXTRACTION, GROUP_EXTRACTORS)


async def consume_extraction_next() -> tuple[str, dict] | None:
    """Block up to 5s for the next entity_extraction message."""
    msgs = await consume_jobs(
        STREAM_ENTITY_EXTRACTION,
        GROUP_EXTRACTORS,
        _EXTRACTION_CONSUMER,
        count=1,
        block_ms=5000,
    )
    if not msgs:
        return None
    return msgs[0]


async def ack_extraction(msg_id: str) -> None:
    """Acknowledge an entity_extraction message."""
    await ack_job(STREAM_ENTITY_EXTRACTION, GROUP_EXTRACTORS, msg_id)
