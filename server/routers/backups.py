"""
Backup clip management — fallback visuals for unrecognized tracks.

Provides endpoints for generating, listing, and managing genre-specific
backup loops that Resolume can use as fallbacks.
"""
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..database import get_setting, set_setting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backups", tags=["backups"])

# Default backup genres (major DJ genres)
DEFAULT_GENRES = [
    "Universal",
    "House",
    "Techno",
    "DnB / Drum & Bass",
    "Dubstep / Bass",
    "Trance",
    "Hip-Hop / Trap",
    "Ambient / Chill",
]

_BACKUP_KEY = "backup_clips"


def _get_backups() -> list[dict]:
    """Load backup clip state from settings."""
    raw = get_setting(_BACKUP_KEY, "[]")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


def _save_backups(backups: list[dict]):
    set_setting(_BACKUP_KEY, json.dumps(backups))


@router.get("")
def list_backups():
    """List all backup clips and their status."""
    backups = _get_backups()

    # Ensure all default genres exist
    existing_genres = {b["genre"] for b in backups}
    for genre in DEFAULT_GENRES:
        if genre not in existing_genres:
            backups.append({
                "id": uuid.uuid4().hex[:8],
                "genre": genre,
                "status": "not_generated",
                "duration": 60,
                "brand": "example",
                "video_path": None,
                "loopable": False,
                "created_at": None,
            })

    return {"backups": backups, "total": len(backups)}


class GenerateBackupRequest(BaseModel):
    genre: str
    brand: str = "example"
    duration: int = 60
    prompt_override: str = ""


@router.post("/generate")
async def generate_backup(req: GenerateBackupRequest):
    """Queue a backup clip generation for a genre."""
    backups = _get_backups()

    # Find or create the backup entry
    entry = None
    for b in backups:
        if b["genre"] == req.genre:
            entry = b
            break

    if entry is None:
        entry = {
            "id": uuid.uuid4().hex[:8],
            "genre": req.genre,
            "status": "not_generated",
            "duration": req.duration,
            "brand": req.brand,
            "video_path": None,
            "loopable": False,
            "created_at": None,
        }
        backups.append(entry)

    # Mark as queued
    entry["status"] = "queued"
    entry["duration"] = req.duration
    entry["brand"] = req.brand
    if req.prompt_override:
        entry["prompt_override"] = req.prompt_override

    _save_backups(backups)

    # In a real implementation, this would enqueue a generation job.
    # For now, we just mark it as queued for the pipeline to pick up.
    logger.info(f"Backup clip queued for genre: {req.genre}")

    return {"queued": True, "backup": entry}


@router.delete("/{backup_id}")
def delete_backup(backup_id: str):
    """Delete a backup clip."""
    backups = _get_backups()
    original_len = len(backups)
    backups = [b for b in backups if b.get("id") != backup_id]

    if len(backups) == original_len:
        raise HTTPException(404, "Backup not found")

    _save_backups(backups)
    return {"deleted": True, "backup_id": backup_id}


@router.get("/genres")
def list_backup_genres():
    """List default backup genres."""
    return {"genres": DEFAULT_GENRES}
