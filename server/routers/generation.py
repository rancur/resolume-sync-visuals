"""
Job management endpoints — create, list, cancel generation jobs.
"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..database import cancel_job, create_job, get_job, list_jobs, get_setting
from ..services.job_queue import enqueue_job
from ..services.lexicon_service import get_lexicon_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class CreateJobRequest(BaseModel):
    track_id: str
    brand: str = "will_see"
    quality: str = "high"


class BulkJobRequest(BaseModel):
    track_ids: list[str]
    brand: str = "will_see"
    quality: str = "high"


@router.post("")
async def create_single_job(req: CreateJobRequest):
    svc = get_lexicon_service()
    try:
        track = svc.get_track(req.track_id)
    except Exception as exc:
        logger.error(f"Failed to fetch track {req.track_id}: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")
    if not track:
        raise HTTPException(404, f"Track {req.track_id} not found in Lexicon")

    job_id = uuid.uuid4().hex[:12]
    job = create_job(
        job_id=job_id,
        track_title=track.get("title", "Unknown"),
        track_artist=track.get("artist", ""),
        track_id=req.track_id,
        brand=req.brand,
        quality=req.quality,
    )
    await enqueue_job(job_id, track, brand=req.brand, quality=req.quality)
    return job


@router.post("/bulk")
async def create_bulk_jobs(req: BulkJobRequest):
    svc = get_lexicon_service()
    jobs = []
    errors = []

    for tid in req.track_ids:
        try:
            track = svc.get_track(tid)
        except Exception as exc:
            logger.error(f"Failed to fetch track {tid}: {exc}")
            errors.append({"track_id": tid, "error": f"Lexicon unavailable: {exc}"})
            continue
        if not track:
            errors.append({"track_id": tid, "error": "Not found"})
            continue

        job_id = uuid.uuid4().hex[:12]
        job = create_job(
            job_id=job_id,
            track_title=track.get("title", "Unknown"),
            track_artist=track.get("artist", ""),
            track_id=tid,
            brand=req.brand,
            quality=req.quality,
        )
        await enqueue_job(job_id, track, brand=req.brand, quality=req.quality)
        jobs.append(job)

    return {"jobs": jobs, "errors": errors}


@router.get("")
def list_all_jobs(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return {"jobs": list_jobs(status=status, limit=limit, offset=offset)}


@router.get("/{job_id}")
def get_single_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.delete("/{job_id}")
def cancel_single_job(job_id: str):
    success = cancel_job(job_id)
    if not success:
        raise HTTPException(
            400, "Job cannot be cancelled (already completed or not found)"
        )
    return {"cancelled": True, "job_id": job_id}


@router.post("/estimate")
def estimate_generation_cost(req: CreateJobRequest):
    """Estimate cost before starting generation. Returns cost breakdown."""
    from src.cost_guard import CostGuard

    svc = get_lexicon_service()
    try:
        track = svc.get_track(req.track_id)
    except Exception as exc:
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")
    if not track:
        raise HTTPException(404, f"Track {req.track_id} not found")

    duration = track.get("duration", 180)
    max_cost = float(get_setting("cost_cap_per_song", "30.0"))
    auto_downgrade = get_setting("cost_auto_downgrade", "true") == "true"

    # Get current default video model
    default_model = get_setting("default_video_model", "kling-v1")

    guard = CostGuard(max_cost=max_cost, auto_downgrade=auto_downgrade)
    estimate = guard.estimate_cost(
        model=default_model,
        duration=duration,
        segment_length=5.0,
    )

    return {
        "track_id": req.track_id,
        "track_title": track.get("title", "Unknown"),
        "duration": duration,
        "model": estimate.model,
        "total_segments": estimate.total_segments,
        "keyframe_cost": round(estimate.keyframe_cost, 4),
        "video_cost": round(estimate.video_cost, 4),
        "total_estimated": round(estimate.total_estimated, 2),
        "budget_limit": estimate.budget_limit,
        "exceeds_budget": estimate.exceeds_budget,
        "suggested_model": estimate.suggested_model,
        "suggested_cost": round(estimate.suggested_cost, 2) if estimate.suggested_cost else None,
        "warning": estimate.warning,
    }


@router.post("/{job_id}/retry")
async def retry_failed_job(job_id: str):
    """Retry a failed job by creating a new one with the same parameters."""
    old_job = get_job(job_id)
    if not old_job:
        raise HTTPException(404, "Job not found")
    if old_job["status"] != "failed":
        raise HTTPException(400, "Only failed jobs can be retried")

    track_id = old_job.get("track_id", "")
    if not track_id:
        raise HTTPException(400, "Original job has no track_id — cannot retry")

    svc = get_lexicon_service()
    try:
        track = svc.get_track(track_id)
    except Exception as exc:
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")
    if not track:
        raise HTTPException(404, f"Track {track_id} no longer found in Lexicon")

    new_job_id = uuid.uuid4().hex[:12]
    brand = old_job.get("brand", "will_see")
    quality = old_job.get("quality", "high")

    job = create_job(
        job_id=new_job_id,
        track_title=track.get("title", "Unknown"),
        track_artist=track.get("artist", ""),
        track_id=track_id,
        brand=brand,
        quality=quality,
    )
    await enqueue_job(new_job_id, track, brand=brand, quality=quality)
    return {"retried": True, "old_job_id": job_id, "new_job": job}
