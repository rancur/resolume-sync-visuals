"""
Setlist management endpoints.
Issue #48: Set-list aware compositions with transition planning.
"""
import json
import logging
import time
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setlists", tags=["setlists"])


def _init_setlists_table():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS setlists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                tracks TEXT DEFAULT '[]',
                transitions TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)


try:
    _init_setlists_table()
except Exception:
    pass


class CreateSetlistRequest(BaseModel):
    name: str
    description: str = ""
    tracks: list[dict] = []
    transitions: dict = {}


class UpdateSetlistRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tracks: Optional[list[dict]] = None
    transitions: Optional[dict] = None


class ReorderRequest(BaseModel):
    track_order: list[str]  # list of track IDs in new order


TRANSITION_TYPES = ["crossfade", "hard_cut", "color_wash", "zoom_through", "fade_black"]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_setlist(row) -> dict:
    d = dict(row)
    d["tracks"] = json.loads(d.get("tracks", "[]"))
    d["transitions"] = json.loads(d.get("transitions", "{}"))
    return d


@router.get("")
def list_setlists(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    _init_setlists_table()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM setlists ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM setlists").fetchone()[0]
        return {"setlists": [_parse_setlist(r) for r in rows], "total": total}


@router.post("")
def create_setlist(req: CreateSetlistRequest):
    _init_setlists_table()
    setlist_id = uuid.uuid4().hex[:12]
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO setlists (id, name, description, tracks, transitions, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (setlist_id, req.name, req.description,
             json.dumps(req.tracks), json.dumps(req.transitions), now, now),
        )
    return _get_setlist(setlist_id)


@router.get("/transition-types")
def get_transition_types():
    return {"types": TRANSITION_TYPES}


@router.get("/{setlist_id}")
def get_setlist(setlist_id: str):
    s = _get_setlist(setlist_id)
    if not s:
        raise HTTPException(404, "Setlist not found")
    return s


@router.put("/{setlist_id}")
def update_setlist(setlist_id: str, req: UpdateSetlistRequest):
    existing = _get_setlist(setlist_id)
    if not existing:
        raise HTTPException(404, "Setlist not found")

    updates = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.description is not None:
        updates["description"] = req.description
    if req.tracks is not None:
        updates["tracks"] = json.dumps(req.tracks)
    if req.transitions is not None:
        updates["transitions"] = json.dumps(req.transitions)

    if updates:
        updates["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [setlist_id]
        with get_db() as conn:
            conn.execute(f"UPDATE setlists SET {cols} WHERE id = ?", vals)

    return _get_setlist(setlist_id)


@router.delete("/{setlist_id}")
def delete_setlist(setlist_id: str):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM setlists WHERE id = ?", (setlist_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Setlist not found")
    return {"deleted": True, "id": setlist_id}


@router.post("/{setlist_id}/reorder")
def reorder_tracks(setlist_id: str, req: ReorderRequest):
    """Reorder tracks in a setlist."""
    existing = _get_setlist(setlist_id)
    if not existing:
        raise HTTPException(404, "Setlist not found")

    tracks = existing["tracks"]
    track_map = {t["id"]: t for t in tracks if isinstance(t, dict) and "id" in t}

    reordered = []
    for tid in req.track_order:
        if tid in track_map:
            reordered.append(track_map[tid])

    # Add any tracks not in the new order at the end
    seen = set(req.track_order)
    for t in tracks:
        if isinstance(t, dict) and t.get("id") not in seen:
            reordered.append(t)

    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE setlists SET tracks = ?, updated_at = ? WHERE id = ?",
            (json.dumps(reordered), now, setlist_id),
        )
    return _get_setlist(setlist_id)


@router.post("/{setlist_id}/transition")
def set_transition(setlist_id: str, from_track: str, to_track: str, transition_type: str = "crossfade"):
    """Set transition type between two adjacent tracks."""
    existing = _get_setlist(setlist_id)
    if not existing:
        raise HTTPException(404, "Setlist not found")

    if transition_type not in TRANSITION_TYPES:
        raise HTTPException(400, f"Invalid transition type. Must be one of: {TRANSITION_TYPES}")

    transitions = existing["transitions"]
    key = f"{from_track}->{to_track}"
    transitions[key] = {
        "type": transition_type,
        "from_track": from_track,
        "to_track": to_track,
    }

    now = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE setlists SET transitions = ?, updated_at = ? WHERE id = ?",
            (json.dumps(transitions), now, setlist_id),
        )
    return _get_setlist(setlist_id)


@router.post("/{setlist_id}/build-avc")
def build_setlist_avc(setlist_id: str):
    """Build a Resolume .avc composition for the setlist with transitions."""
    existing = _get_setlist(setlist_id)
    if not existing:
        raise HTTPException(404, "Setlist not found")

    tracks = existing["tracks"]
    transitions = existing["transitions"]

    if not tracks:
        raise HTTPException(400, "Setlist has no tracks")

    # Build the AVC XML for the setlist
    avc_xml = _build_setlist_avc_xml(existing["name"], tracks, transitions)

    return {
        "success": True,
        "setlist_id": setlist_id,
        "track_count": len(tracks),
        "transition_count": len(transitions),
        "avc_preview": avc_xml[:2000],
    }


def _get_setlist(setlist_id: str) -> Optional[dict]:
    _init_setlists_table()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM setlists WHERE id = ?", (setlist_id,)).fetchone()
        if not row:
            return None
        return _parse_setlist(row)


def _build_setlist_avc_xml(name: str, tracks: list, transitions: dict) -> str:
    """Generate a Resolume AVC XML with transition clips between tracks."""
    layers_xml = []

    # Main video layer
    for i, track in enumerate(tracks):
        title = track.get("title", f"Track {i+1}")
        layers_xml.append(f'    <clip name="{title}" column="{i}" />')

    # Transition layer
    for i in range(len(tracks) - 1):
        t_key = f"{tracks[i].get('id', i)}->{tracks[i+1].get('id', i+1)}"
        t_info = transitions.get(t_key, {"type": "crossfade"})
        t_type = t_info.get("type", "crossfade") if isinstance(t_info, dict) else "crossfade"
        layers_xml.append(
            f'    <!-- Transition: {tracks[i].get("title", "")} -> {tracks[i+1].get("title", "")} [{t_type}] -->'
        )

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<composition name="{name}" width="1920" height="1080">\n'
        f'  <layer id="1" name="Main Video">\n'
        + "\n".join(layers_xml[:len(tracks)])
        + "\n  </layer>\n"
        + f'  <layer id="2" name="Transitions">\n'
        + "\n".join(layers_xml[len(tracks):])
        + "\n  </layer>\n"
        + "</composition>\n"
    )
