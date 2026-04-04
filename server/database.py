"""
SQLite database for server-side job tracking and persistent settings.
WAL mode for concurrent read/write access.
"""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from .config import get_settings

_DB_FILE = "server.db"


def _db_path() -> Path:
    settings = get_settings()
    return settings.db_dir / _DB_FILE


@contextmanager
def get_db():
    """Context manager for a WAL-mode SQLite connection."""
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                track_title TEXT NOT NULL,
                track_artist TEXT DEFAULT '',
                track_id TEXT DEFAULT '',
                brand TEXT DEFAULT 'example',
                quality TEXT DEFAULT 'high',
                status TEXT DEFAULT 'queued',
                progress REAL DEFAULT 0.0,
                progress_message TEXT DEFAULT '',
                cost REAL DEFAULT 0.0,
                error TEXT DEFAULT '',
                result_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_status
            ON jobs(status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_jobs_created
            ON jobs(created_at DESC)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS track_prompts (
                track_id TEXT PRIMARY KEY,
                global_prompt TEXT DEFAULT '',
                section_prompts TEXT DEFAULT '{}',
                updated_at TEXT NOT NULL
            )
        """)


# ── Job helpers ──

def create_job(
    job_id: str,
    track_title: str,
    track_artist: str = "",
    track_id: str = "",
    brand: str = "example",
    quality: str = "high",
) -> dict:
    now = _now()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO jobs
               (id, track_title, track_artist, track_id, brand, quality,
                status, progress, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'queued', 0.0, ?)""",
            (job_id, track_title, track_artist, track_id, brand, quality, now),
        )
    return get_job(job_id)


def get_job(job_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def list_jobs(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]


def update_job(job_id: str, **fields):
    if not fields:
        return
    allowed = {
        "status", "progress", "progress_message", "cost",
        "error", "result_json", "started_at", "completed_at",
    }
    cols = []
    vals = []
    for k, v in fields.items():
        if k in allowed:
            cols.append(f"{k} = ?")
            vals.append(v)
    if not cols:
        return
    vals.append(job_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(cols)} WHERE id = ?",
            vals,
        )


def cancel_job(job_id: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'cancelled', completed_at = ? "
            "WHERE id = ? AND status IN ('queued', 'running')",
            (_now(), job_id),
        )
        return cur.rowcount > 0


# ── Settings helpers ──

def get_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default


def set_setting(key: str, value: str):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
            (key, value, _now(), value, _now()),
        )


def get_all_settings() -> dict:
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row[0]: row[1] for row in rows}


# ── Track prompt helpers ──

def get_track_prompt(track_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM track_prompts WHERE track_id = ?", (track_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["section_prompts"] = json.loads(d.get("section_prompts", "{}"))
        except (json.JSONDecodeError, TypeError):
            d["section_prompts"] = {}
        return d


def set_track_prompt(
    track_id: str,
    global_prompt: str = "",
    section_prompts: Optional[dict] = None,
):
    now = _now()
    sections_json = json.dumps(section_prompts or {})
    with get_db() as conn:
        conn.execute(
            """INSERT INTO track_prompts (track_id, global_prompt, section_prompts, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(track_id) DO UPDATE SET
                   global_prompt = ?, section_prompts = ?, updated_at = ?""",
            (track_id, global_prompt, sections_json, now,
             global_prompt, sections_json, now),
        )


def delete_track_prompt(track_id: str) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM track_prompts WHERE track_id = ?", (track_id,)
        )
        return cur.rowcount > 0


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
