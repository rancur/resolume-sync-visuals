"""
Genre exploration endpoints — browse tracks by genre with visual generation stats.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..services.lexicon_service import get_lexicon_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/genres", tags=["genres"])


@router.get("")
def list_genres():
    """Return all genres with track count and visual generation stats."""
    svc = get_lexicon_service()
    try:
        svc._ensure_full_cache()
        tracks = svc._track_cache or []

        genre_stats: dict[str, dict] = {}
        for t in tracks:
            g = t.get("genre")
            if not g:
                continue
            if g not in genre_stats:
                genre_stats[g] = {
                    "genre": g,
                    "track_count": 0,
                    "with_visuals": 0,
                    "total_bpm": 0.0,
                    "total_energy": 0.0,
                    "bpm_count": 0,
                    "energy_count": 0,
                }
            stats = genre_stats[g]
            stats["track_count"] += 1

            if t.get("has_video") is True:
                stats["with_visuals"] += 1

            bpm = t.get("bpm")
            if bpm and isinstance(bpm, (int, float)) and bpm > 0:
                stats["total_bpm"] += bpm
                stats["bpm_count"] += 1

            energy = t.get("energy")
            if energy is not None and isinstance(energy, (int, float)):
                stats["total_energy"] += energy
                stats["energy_count"] += 1

        result = []
        for stats in genre_stats.values():
            avg_bpm = round(stats["total_bpm"] / stats["bpm_count"], 1) if stats["bpm_count"] > 0 else 0
            avg_energy = round(stats["total_energy"] / stats["energy_count"], 1) if stats["energy_count"] > 0 else 0
            pct = round((stats["with_visuals"] / stats["track_count"]) * 100, 1) if stats["track_count"] > 0 else 0
            result.append({
                "genre": stats["genre"],
                "track_count": stats["track_count"],
                "with_visuals": stats["with_visuals"],
                "visual_pct": pct,
                "avg_bpm": avg_bpm,
                "avg_energy": avg_energy,
            })

        result.sort(key=lambda x: x["genre"])
        return {"genres": result, "total": len(result)}

    except Exception as exc:
        logger.error(f"Failed to fetch genre stats: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")


@router.get("/{genre}/tracks")
def get_genre_tracks(
    genre: str,
    sort_by: str = "title",
    sort_desc: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return tracks for a specific genre."""
    svc = get_lexicon_service()
    try:
        return svc.get_tracks(
            genre=genre,
            sort_by=sort_by,
            sort_desc=sort_desc,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.error(f"Failed to fetch genre tracks: {exc}")
        raise HTTPException(502, f"Lexicon API unavailable: {exc}")
