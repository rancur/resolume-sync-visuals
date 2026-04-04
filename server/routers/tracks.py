"""
Track library endpoints — pull from Lexicon, joined with NAS video status.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..database import get_track_prompt, set_track_prompt, delete_track_prompt, get_db
from ..services.lexicon_service import get_lexicon_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tracks", tags=["tracks"])


@router.get("")
def list_tracks(
    search: str = "",
    sort_by: str = "title",
    sort_desc: bool = False,
    genre: str = "",
    has_video: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    svc = get_lexicon_service()
    try:
        return svc.get_tracks(
            search=search,
            sort_by=sort_by,
            sort_desc=sort_desc,
            genre=genre,
            has_video=has_video,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error(f"Failed to fetch tracks: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")


@router.get("/genres")
def list_genres():
    """Return all unique genres in the library."""
    svc = get_lexicon_service()
    try:
        return {"genres": svc.get_genres()}
    except Exception as exc:
        logger.error(f"Failed to fetch genres: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")


@router.get("/{track_id}")
def get_track(track_id: str):
    svc = get_lexicon_service()
    try:
        track = svc.get_track(track_id)
    except Exception as exc:
        logger.error(f"Failed to fetch track {track_id}: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")
    if not track:
        raise HTTPException(404, "Track not found")
    return track


# ── Per-track custom prompts ──


class TrackPromptRequest(BaseModel):
    global_prompt: str = ""
    section_prompts: dict[str, str] = {}


@router.get("/{track_id}/prompt")
def get_prompt(track_id: str):
    """Get the custom prompt for a track."""
    data = get_track_prompt(track_id)
    if not data:
        return {
            "track_id": track_id,
            "global_prompt": "",
            "section_prompts": {},
        }
    return data


@router.put("/{track_id}/prompt")
def set_prompt(track_id: str, req: TrackPromptRequest):
    """Set or update the custom prompt for a track."""
    set_track_prompt(
        track_id=track_id,
        global_prompt=req.global_prompt,
        section_prompts=req.section_prompts,
    )
    return get_track_prompt(track_id)


@router.delete("/{track_id}/prompt")
def clear_prompt(track_id: str):
    """Remove the custom prompt for a track."""
    delete_track_prompt(track_id)
    return {"deleted": True, "track_id": track_id}


@router.get("/{track_id}/history")
def get_track_history(track_id: str, limit: int = Query(50, ge=1, le=200)):
    """Get generation history for a specific track (jobs + cost data)."""
    history = []

    # Get all jobs for this track
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, track_title, track_artist, brand, quality, status,
                      progress, cost, error, result_json,
                      created_at, started_at, completed_at
               FROM jobs WHERE track_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (track_id, limit),
        ).fetchall()
        for r in rows:
            row = dict(r)
            # Calculate duration
            duration_secs = None
            if row.get("started_at") and row.get("completed_at"):
                try:
                    import time as _time
                    start_t = _time.mktime(_time.strptime(row["started_at"], "%Y-%m-%dT%H:%M:%SZ"))
                    end_t = _time.mktime(_time.strptime(row["completed_at"], "%Y-%m-%dT%H:%M:%SZ"))
                    duration_secs = round(end_t - start_t, 1)
                except Exception:
                    pass

            # Parse result for model info
            result = {}
            try:
                import json as _json
                result = _json.loads(row.get("result_json", "{}") or "{}")
            except Exception:
                pass

            # Check if video exists
            has_video = bool(result.get("nas_path") or result.get("local_vj_path"))

            history.append({
                "id": row["id"],
                "status": row["status"],
                "brand": row.get("brand", ""),
                "quality": row.get("quality", ""),
                "model": result.get("model", row.get("brand", "")),
                "cost": row.get("cost", 0) or 0,
                "error": row.get("error", ""),
                "duration_secs": duration_secs,
                "has_video": has_video,
                "video_path": result.get("nas_path", ""),
                "created_at": row.get("created_at", ""),
                "started_at": row.get("started_at", ""),
                "completed_at": row.get("completed_at", ""),
                "segments": result.get("segments", 0),
            })

    # Also get per-call cost data from the cost tracker
    cost_details = []
    try:
        from src.tracking import CostTracker
        from ..config import get_settings
        from pathlib import Path
        settings = get_settings()
        tracker = CostTracker(db_path=Path(settings.db_path) / "costs.db")

        # Get track title to look up costs
        svc = get_lexicon_service()
        track = svc.get_track(track_id)
        if track:
            track_name = track.get("title", "")
            if track_name:
                with tracker._conn() as conn:
                    cost_rows = conn.execute(
                        """SELECT timestamp, model, cost_usd, phrase_idx, phrase_label,
                                  style, cached, quality
                           FROM api_calls WHERE track_name = ?
                           ORDER BY timestamp DESC LIMIT ?""",
                        (track_name, limit),
                    ).fetchall()
                    cost_details = [dict(r) for r in cost_rows]
    except Exception as exc:
        logger.debug(f"Cost detail lookup failed: {exc}")

    return {
        "track_id": track_id,
        "jobs": history,
        "cost_details": cost_details,
        "total_jobs": len(history),
        "total_cost": sum(h.get("cost", 0) for h in history),
    }


@router.get("/{track_id}/metadata")
def get_track_metadata(track_id: str):
    """Get rich generation metadata for a track (from metadata.json on NAS or local output)."""
    import json as _json
    from pathlib import Path

    # Try to find metadata.json alongside the track's video
    # Check the jobs table for the latest completed job with a result
    with get_db() as conn:
        row = conn.execute(
            """SELECT result_json FROM jobs
               WHERE track_id = ? AND status = 'completed' AND result_json IS NOT NULL
               ORDER BY completed_at DESC LIMIT 1""",
            (track_id,),
        ).fetchone()

    if not row:
        return {"track_id": track_id, "metadata": None, "error": "No completed generation found"}

    result = {}
    try:
        result = _json.loads(row["result_json"] or "{}")
    except Exception:
        pass

    # Look for metadata.json in the same directory as the video
    metadata = None
    for path_key in ("nas_path", "local_vj_path", "output_dir"):
        video_path = result.get(path_key, "")
        if not video_path:
            continue
        # metadata.json should be alongside or one level up
        for candidate in [
            Path(video_path).parent / "metadata.json",
            Path(video_path).with_suffix(".json"),
        ]:
            if candidate.exists():
                try:
                    metadata = _json.loads(candidate.read_text())
                    break
                except Exception as exc:
                    logger.debug(f"Failed to read metadata from {candidate}: {exc}")
        if metadata:
            break

    if metadata:
        return {"track_id": track_id, "metadata": metadata}
    return {"track_id": track_id, "metadata": None, "error": "metadata.json not found"}


@router.get("/{track_id}/colors")
def get_track_colors(track_id: str, n_colors: int = Query(6, ge=2, le=12)):
    """Extract color palette from the track's album art."""
    from src.analyzer.color_palette import extract_palette_from_audio

    svc = get_lexicon_service()
    try:
        track = svc.get_track(track_id)
    except Exception as exc:
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")
    if not track:
        raise HTTPException(404, "Track not found")

    location = track.get("location", "")
    if not location:
        return {"track_id": track_id, "palette": [], "error": "No file location available"}

    palette = extract_palette_from_audio(location, n_colors=n_colors)
    if palette is None:
        return {"track_id": track_id, "palette": [], "error": "No album art found in audio file"}

    return {"track_id": track_id, "palette": palette}


# Playlist endpoints live here too for convenience

playlist_router = APIRouter(prefix="/api/playlists", tags=["playlists"])


@playlist_router.get("")
def list_playlists():
    svc = get_lexicon_service()
    try:
        return {"playlists": svc.get_playlists()}
    except Exception as exc:
        logger.error(f"Failed to fetch playlists: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")


@playlist_router.get("/{playlist_id}/tracks")
def get_playlist_tracks(playlist_id: int):
    svc = get_lexicon_service()
    try:
        tracks = svc.get_playlist_tracks(playlist_id)
    except Exception as exc:
        logger.error(f"Failed to fetch playlist {playlist_id} tracks: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")
    return {"tracks": tracks, "total": len(tracks)}
