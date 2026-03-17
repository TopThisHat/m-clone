from __future__ import annotations

import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app.auth import get_current_user
from app.db import (
    DatabaseNotConfigured,
    db_cancel_job,
    db_compare_jobs,
    db_create_and_enqueue_validation_job,
    db_export_campaign_results,
    db_get_campaign,
    db_get_entity_cross_campaign,
    db_get_knowledge_for_campaign,
    db_get_queue_job_owner,
    db_get_score_trends,
    db_get_scores,
    db_get_validation_job,
    db_is_team_member,
    db_list_dead_jobs,
    db_list_entities,
    db_list_attributes,
    db_list_results,
    db_list_validation_jobs,
    db_retry_dead_job,
)
from app.models.campaign import JobCreate, JobOut, KnowledgeOut, ResultOut, ScoreOut

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])


def _no_db() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="A database connection is required for this action. Please configure DATABASE_URL.",
    )


async def _get_owned_campaign(campaign_id: str, user_sid: str):
    try:
        campaign = await db_get_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if campaign.get("team_id"):
        if not await db_is_team_member(campaign["team_id"], user_sid):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif campaign["owner_sid"] != user_sid:
        raise HTTPException(status_code=403, detail="Forbidden")
    return campaign


@router.post("/api/campaigns/{campaign_id}/jobs", response_model=JobOut, status_code=201)
async def create_job(campaign_id: str, body: JobCreate, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        entity_ids = body.entity_ids
        attribute_ids = body.attribute_ids
        # Auto-populate from campaign if not provided
        if not entity_ids:
            ent_page = await db_list_entities(campaign_id, limit=0)
            entity_ids = [e["id"] for e in ent_page["items"]]
        if not attribute_ids:
            attr_page = await db_list_attributes(campaign_id, limit=0)
            attribute_ids = [a["id"] for a in attr_page["items"]]
        job = await db_create_and_enqueue_validation_job(
            campaign_id=campaign_id,
            triggered_by="user",
            triggered_sid=user["sub"],
            entity_filter=entity_ids,
            attribute_filter=attribute_ids,
        )
    except DatabaseNotConfigured:
        raise _no_db()

    logger.info("Created and enqueued validation_job %s", job["id"])
    return job


@router.get("/api/campaigns/{campaign_id}/jobs", response_model=list[JobOut])
async def list_jobs(campaign_id: str, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_list_validation_jobs(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/api/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str, user=Depends(get_current_user)):
    try:
        job = await db_get_validation_job(job_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Verify campaign ownership
    await _get_owned_campaign(job["campaign_id"], user["sub"])
    return job


@router.get("/api/jobs/{job_id}/results", response_model=list[ResultOut])
async def get_results(
    job_id: str,
    entity_id: str | None = Query(default=None),
    attribute_id: str | None = Query(default=None),
    present: bool | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0),
    user=Depends(get_current_user),
):
    try:
        job = await db_get_validation_job(job_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _get_owned_campaign(job["campaign_id"], user["sub"])
    try:
        return await db_list_results(
            job_id=job_id,
            entity_id=entity_id,
            attribute_id=attribute_id,
            present=present,
            limit=limit,
            offset=offset,
        )
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/api/campaigns/{campaign_id}/scores", response_model=list[ScoreOut])
async def get_scores(campaign_id: str, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_get_scores(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, user=Depends(get_current_user)):
    try:
        job = await db_get_validation_job(job_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await _get_owned_campaign(job["campaign_id"], user["sub"])
    try:
        cancelled = await db_cancel_job(job_id)
    except DatabaseNotConfigured:
        raise _no_db()
    return {"cancelled": cancelled}


@router.get("/api/campaigns/{campaign_id}/trends")
async def get_score_trends(
    campaign_id: str,
    entity_id: str | None = Query(default=None),
    user=Depends(get_current_user),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_get_score_trends(campaign_id, entity_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/api/campaigns/{campaign_id}/diff")
async def compare_jobs(
    campaign_id: str,
    job_id_a: str = Query(),
    job_id_b: str = Query(),
    user=Depends(get_current_user),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_compare_jobs(job_id_a, job_id_b)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/api/campaigns/{campaign_id}/export")
async def export_campaign_results(
    campaign_id: str,
    format: str = Query(default="csv"),
    user=Depends(get_current_user),
):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        rows = await db_export_campaign_results(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Entity", "GWM ID", "Attribute", "Present", "Confidence",
        "Evidence", "Score", "Attrs Present", "Attrs Checked", "Date",
    ])
    for r in rows:
        writer.writerow([
            r.get("entity_label", ""),
            r.get("gwm_id", ""),
            r.get("attribute_label", ""),
            r.get("present", ""),
            f"{r['confidence']:.2f}" if r.get("confidence") is not None else "",
            r.get("evidence", ""),
            f"{r['total_score']:.2f}" if r.get("total_score") is not None else "",
            r.get("attributes_present", ""),
            r.get("attributes_checked", ""),
            str(r["created_at"]) if r.get("created_at") else "",
        ])

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="campaign-{campaign_id}-results.csv"'},
    )


@router.get("/api/campaigns/{campaign_id}/dead-jobs")
async def list_dead_jobs(campaign_id: str, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_list_dead_jobs(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.post("/api/jobs/{job_id}/retry")
async def retry_dead_job(job_id: str, user=Depends(get_current_user)):
    try:
        row = await db_get_queue_job_owner(job_id)
    except DatabaseNotConfigured:
        raise _no_db()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    await _get_owned_campaign(str(row["campaign_id"]), user["sub"])
    try:
        retried = await db_retry_dead_job(job_id)
    except DatabaseNotConfigured:
        raise _no_db()
    return {"retried": retried}


@router.get("/api/campaigns/{campaign_id}/knowledge", response_model=list[KnowledgeOut])
async def get_knowledge(campaign_id: str, user=Depends(get_current_user)):
    await _get_owned_campaign(campaign_id, user["sub"])
    try:
        return await db_get_knowledge_for_campaign(campaign_id)
    except DatabaseNotConfigured:
        raise _no_db()


@router.get("/api/entities/cross-campaign/{gwm_id}")
async def get_entity_cross_campaign(gwm_id: str, user=Depends(get_current_user)):
    try:
        return await db_get_entity_cross_campaign(gwm_id)
    except DatabaseNotConfigured:
        raise _no_db()
