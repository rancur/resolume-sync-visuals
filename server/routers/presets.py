"""
Preset management endpoints — save and apply reusable visual presets.
Issue #47: Favorite styles and reusable visual presets.
"""
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..config import get_settings
from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _init_presets_table():
    """Create presets table if it doesn't exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS presets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'user',
                prompt TEXT DEFAULT '',
                model TEXT DEFAULT '',
                motion_settings TEXT DEFAULT '{}',
                style_reference TEXT DEFAULT '',
                color_palette TEXT DEFAULT '[]',
                brand_overrides TEXT DEFAULT '{}',
                thumbnail_url TEXT DEFAULT '',
                use_count INTEGER DEFAULT 0,
                is_favorite INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_presets_favorite
            ON presets(is_favorite DESC, use_count DESC)
        """)


# Ensure table exists on import
try:
    _init_presets_table()
except Exception:
    pass  # DB may not be initialized yet; init_db will handle it


class CreatePresetRequest(BaseModel):
    name: str
    description: str = ""
    category: str = "user"
    prompt: str = ""
    model: str = ""
    motion_settings: dict = {}
    style_reference: str = ""
    color_palette: list = []
    brand_overrides: dict = {}
    thumbnail_url: str = ""


class UpdatePresetRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    motion_settings: Optional[dict] = None
    style_reference: Optional[str] = None
    color_palette: Optional[list] = None
    brand_overrides: Optional[dict] = None
    thumbnail_url: Optional[str] = None
    is_favorite: Optional[bool] = None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@router.get("")
def list_presets(
    category: Optional[str] = None,
    favorites_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all presets, optionally filtered by category or favorites."""
    _init_presets_table()
    with get_db() as conn:
        conditions = []
        params = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if favorites_only:
            conditions.append("is_favorite = 1")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM presets {where} ORDER BY is_favorite DESC, use_count DESC, created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) FROM presets {where}",
            params,
        ).fetchone()[0]

        presets = []
        for row in rows:
            p = dict(row)
            p["motion_settings"] = json.loads(p.get("motion_settings", "{}"))
            p["color_palette"] = json.loads(p.get("color_palette", "[]"))
            p["brand_overrides"] = json.loads(p.get("brand_overrides", "{}"))
            p["is_favorite"] = bool(p.get("is_favorite", 0))
            presets.append(p)

        return {"presets": presets, "total": total}


@router.post("")
def create_preset(req: CreatePresetRequest):
    """Create a new preset."""
    _init_presets_table()
    preset_id = uuid.uuid4().hex[:12]
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO presets
               (id, name, description, category, prompt, model,
                motion_settings, style_reference, color_palette,
                brand_overrides, thumbnail_url, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                preset_id, req.name, req.description, req.category,
                req.prompt, req.model,
                json.dumps(req.motion_settings), req.style_reference,
                json.dumps(req.color_palette), json.dumps(req.brand_overrides),
                req.thumbnail_url, now, now,
            ),
        )
    return _get_preset(preset_id)


@router.get("/{preset_id}")
def get_preset(preset_id: str):
    """Get a single preset by ID."""
    preset = _get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    return preset


@router.put("/{preset_id}")
def update_preset(preset_id: str, req: UpdatePresetRequest):
    """Update a preset."""
    existing = _get_preset(preset_id)
    if not existing:
        raise HTTPException(404, "Preset not found")

    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.description is not None:
        updates["description"] = req.description
    if req.category is not None:
        updates["category"] = req.category
    if req.prompt is not None:
        updates["prompt"] = req.prompt
    if req.model is not None:
        updates["model"] = req.model
    if req.motion_settings is not None:
        updates["motion_settings"] = json.dumps(req.motion_settings)
    if req.style_reference is not None:
        updates["style_reference"] = req.style_reference
    if req.color_palette is not None:
        updates["color_palette"] = json.dumps(req.color_palette)
    if req.brand_overrides is not None:
        updates["brand_overrides"] = json.dumps(req.brand_overrides)
    if req.thumbnail_url is not None:
        updates["thumbnail_url"] = req.thumbnail_url
    if req.is_favorite is not None:
        updates["is_favorite"] = 1 if req.is_favorite else 0

    if updates:
        updates["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [preset_id]
        with get_db() as conn:
            conn.execute(f"UPDATE presets SET {cols} WHERE id = ?", vals)

    return _get_preset(preset_id)


@router.delete("/{preset_id}")
def delete_preset(preset_id: str):
    """Delete a preset."""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Preset not found")
    return {"deleted": True, "id": preset_id}


@router.post("/{preset_id}/favorite")
def toggle_favorite(preset_id: str):
    """Toggle favorite status on a preset."""
    preset = _get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")

    new_fav = not preset.get("is_favorite", False)
    with get_db() as conn:
        conn.execute(
            "UPDATE presets SET is_favorite = ?, updated_at = ? WHERE id = ?",
            (1 if new_fav else 0, _now(), preset_id),
        )
    return {"id": preset_id, "is_favorite": new_fav}


@router.post("/{preset_id}/use")
def record_use(preset_id: str):
    """Increment use count for a preset."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE presets SET use_count = use_count + 1, updated_at = ? WHERE id = ?",
            (_now(), preset_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Preset not found")
    return _get_preset(preset_id)


def _get_preset(preset_id: str) -> Optional[dict]:
    _init_presets_table()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
        if not row:
            return None
        p = dict(row)
        p["motion_settings"] = json.loads(p.get("motion_settings", "{}"))
        p["color_palette"] = json.loads(p.get("color_palette", "[]"))
        p["brand_overrides"] = json.loads(p.get("brand_overrides", "{}"))
        p["is_favorite"] = bool(p.get("is_favorite", 0))
        return p
