"""
Preview pipeline endpoints — two-pass progressive rendering.

Pass 1 (preview): Generate keyframe images per segment at draft quality.
                  Fast (~30s/track), cheap (~15% of full cost).
Pass 2 (final):   On approval, generate full video at high quality,
                  reusing preview keyframes as conditioning.
"""
import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from ..services.lexicon_service import get_lexicon_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/preview", tags=["preview"])


class KeyframeRequest(BaseModel):
    brand: str = "example"
    quality: str = "draft"
    sections: list[str] | None = None  # which sections to preview, None = all


class ApproveRequest(BaseModel):
    brand: str = "example"
    quality: str = "high"
    auto_approve: bool = False


class SavingsRequest(BaseModel):
    track_duration: float = 180.0
    preview_quality: str = "draft"
    final_quality: str = "high"
    approval_rate: float = 0.7


@router.post("/{track_id}/keyframes")
async def generate_keyframes(track_id: str, req: KeyframeRequest):
    """Generate preview keyframe images for a track (no video, fast and cheap).

    Returns segment plan with prompts, estimated costs, and preview status.
    Actual keyframe generation happens async via the job queue.
    """
    svc = get_lexicon_service()
    try:
        track = svc.get_track(track_id)
    except Exception as exc:
        logger.error(f"Failed to fetch track {track_id}: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")
    if not track:
        raise HTTPException(404, "Track not found")

    from src.generator.quality_profiles import get_quality_profile, PreviewResult

    try:
        profile = get_quality_profile(req.quality)
    except ValueError as e:
        raise HTTPException(400, str(e))

    title = track.get("title", "Unknown")
    duration = track.get("duration", 180.0)

    # Build segment plan (dry run — no actual generation)
    segments = _plan_preview_segments(track, req.brand, req.sections)

    preview = PreviewResult(
        track_id=track_id,
        track_title=title,
        quality=req.quality,
        segments=segments,
        keyframe_paths=[],
        estimated_final_cost=profile.estimated_cost_per_track(duration),
        preview_cost=get_quality_profile("draft").estimated_cost_per_track(duration),
        status="planned",
    )

    return {
        **preview.to_dict(),
        "profile": {
            "name": profile.name,
            "resolution": profile.resolution_str,
            "video_model": profile.video_model,
            "video_enabled": profile.video_enabled,
            "description": profile.description,
        },
    }


@router.post("/{track_id}/approve")
async def approve_preview(track_id: str, req: ApproveRequest):
    """Approve a preview and kick off full video generation.

    If auto_approve is True, creates a job that skips preview entirely.
    """
    from ..database import create_job
    from ..services.job_queue import enqueue_job
    from src.generator.quality_profiles import get_quality_profile

    svc = get_lexicon_service()
    try:
        track = svc.get_track(track_id)
    except Exception as exc:
        logger.error(f"Failed to fetch track {track_id}: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")
    if not track:
        raise HTTPException(404, "Track not found")

    try:
        profile = get_quality_profile(req.quality)
    except ValueError as e:
        raise HTTPException(400, str(e))

    job_id = uuid.uuid4().hex[:12]
    job = create_job(
        job_id=job_id,
        track_title=track.get("title", "Unknown"),
        track_artist=track.get("artist", ""),
        track_id=track_id,
        brand=req.brand,
        quality=req.quality,
    )
    await enqueue_job(job_id, track, brand=req.brand, quality=req.quality)

    return {
        "job": job,
        "quality_profile": {
            "name": profile.name,
            "resolution": profile.resolution_str,
            "video_model": profile.video_model,
            "description": profile.description,
        },
        "auto_approved": req.auto_approve,
        "message": f"Full generation started at {profile.name} quality ({profile.resolution_str})",
    }


@router.get("/profiles")
async def list_quality_profiles():
    """List all available quality profiles with cost estimates."""
    from src.generator.quality_profiles import QUALITY_PROFILES

    profiles = []
    for name, profile in QUALITY_PROFILES.items():
        profiles.append({
            "name": profile.name,
            "resolution": profile.resolution_str,
            "fps": profile.fps,
            "video_model": profile.video_model,
            "video_enabled": profile.video_enabled,
            "cost_multiplier": profile.cost_multiplier,
            "description": profile.description,
            "estimated_cost_3min": round(profile.estimated_cost_per_track(180.0), 4),
        })
    return {"profiles": profiles}


@router.post("/savings")
async def estimate_savings(req: SavingsRequest):
    """Calculate cost savings from progressive rendering."""
    from src.generator.quality_profiles import estimate_savings as calc_savings

    try:
        result = calc_savings(
            track_duration=req.track_duration,
            preview_quality=req.preview_quality,
            final_quality=req.final_quality,
            approval_rate=req.approval_rate,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return result


def _plan_preview_segments(
    track: dict,
    brand: str,
    sections: list[str] | None,
) -> list[dict]:
    """Plan preview segments without running full audio analysis.

    Uses track metadata (BPM, duration, genre) to create a rough segment
    plan suitable for keyframe preview.
    """
    duration = track.get("duration", 180.0)
    bpm = track.get("bpm", 128.0)
    genre = track.get("genre", "")

    if bpm <= 0:
        bpm = 128.0

    beat_dur = 60.0 / bpm
    phrase_dur = beat_dur * 16  # 16-beat phrases

    segments = []
    t = 0.0
    idx = 0

    while t < duration:
        end = min(t + phrase_dur, duration)
        pos = t / max(duration, 1.0)

        # Assign label based on position in track
        if pos < 0.1:
            label = "intro"
            energy = 0.2
        elif pos < 0.25:
            label = "buildup"
            energy = 0.5
        elif pos < 0.45:
            label = "drop"
            energy = 0.9
        elif pos < 0.55:
            label = "breakdown"
            energy = 0.3
        elif pos < 0.7:
            label = "buildup"
            energy = 0.6
        elif pos < 0.9:
            label = "drop"
            energy = 0.95
        else:
            label = "outro"
            energy = 0.15

        if sections and label not in sections:
            t = end
            idx += 1
            continue

        segments.append({
            "index": idx,
            "label": label,
            "start": round(t, 2),
            "end": round(end, 2),
            "duration": round(end - t, 2),
            "energy": energy,
            "genre": genre,
        })
        t = end
        idx += 1

    return segments
