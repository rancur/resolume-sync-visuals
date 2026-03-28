"""
Render registry — tracks what has been rendered and prevents duplicates.
Hash-based deduplication: track+style+config → output path.

Every render is identified by a deterministic hash of:
  - Audio file content hash (first 1MB + file size)
  - Style name
  - Quality setting
  - Resolution
  - Loop duration beats
  - Phrase index

If a render with the same hash exists and the output file is intact,
the render is skipped entirely.
"""
import hashlib
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".rsv" / "registry.db"


class RenderRegistry:
    """Track all renders for deduplication and status monitoring."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS renders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    render_hash TEXT UNIQUE NOT NULL,
                    audio_hash TEXT NOT NULL,
                    audio_path TEXT NOT NULL,
                    track_name TEXT NOT NULL,
                    style TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    fps INTEGER NOT NULL,
                    loop_beats INTEGER NOT NULL,
                    backend TEXT NOT NULL,
                    phrase_idx INTEGER DEFAULT -1,
                    phrase_label TEXT DEFAULT '',
                    output_path TEXT,
                    output_size INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    cost_usd REAL DEFAULT 0,
                    api_calls INTEGER DEFAULT 0,
                    cache_hits INTEGER DEFAULT 0,
                    started_at TEXT,
                    completed_at TEXT,
                    error_message TEXT,
                    metadata_json TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS track_renders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audio_hash TEXT NOT NULL,
                    audio_path TEXT NOT NULL,
                    track_name TEXT NOT NULL,
                    style TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    total_phrases INTEGER DEFAULT 0,
                    completed_phrases INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    total_cost REAL DEFAULT 0,
                    started_at TEXT,
                    completed_at TEXT,
                    output_dir TEXT,
                    config_json TEXT DEFAULT '{}',
                    UNIQUE(audio_hash, style, quality)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_render_hash ON renders(render_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audio_hash ON renders(audio_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON renders(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_track_audio ON track_renders(audio_hash, style, quality)
            """)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Audio hashing ──

    @staticmethod
    def hash_audio(file_path: str | Path) -> str:
        """
        Fast content hash of an audio file.
        Uses first 1MB + last 1MB + file size for speed on large files.
        """
        file_path = Path(file_path)
        size = file_path.stat().st_size
        h = hashlib.sha256()
        h.update(str(size).encode())

        with open(file_path, "rb") as f:
            # First 1MB
            h.update(f.read(1024 * 1024))
            # Last 1MB
            if size > 2 * 1024 * 1024:
                f.seek(-1024 * 1024, 2)
                h.update(f.read())

        return h.hexdigest()[:16]

    @staticmethod
    def compute_render_hash(
        audio_hash: str,
        style: str,
        quality: str,
        width: int,
        height: int,
        loop_beats: int,
        phrase_idx: int,
        backend: str,
    ) -> str:
        """Deterministic hash for a specific render job."""
        key = f"{audio_hash}:{style}:{quality}:{width}x{height}:{loop_beats}:{phrase_idx}:{backend}"
        return hashlib.sha256(key.encode()).hexdigest()[:20]

    # ── Render tracking ──

    def is_rendered(self, render_hash: str) -> Optional[dict]:
        """
        Check if a render exists and is valid.
        Returns the render record if complete and output exists, else None.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM renders WHERE render_hash = ? AND status = 'completed'",
                (render_hash,),
            ).fetchone()

            if row:
                record = dict(row)
                output_path = record.get("output_path", "")
                if output_path and Path(output_path).exists():
                    return record
                else:
                    # Output file was deleted — mark as invalid
                    conn.execute(
                        "UPDATE renders SET status = 'invalidated' WHERE render_hash = ?",
                        (render_hash,),
                    )
                    return None
            return None

    def start_render(
        self,
        render_hash: str,
        audio_hash: str,
        audio_path: str,
        track_name: str,
        style: str,
        quality: str,
        width: int,
        height: int,
        fps: int,
        loop_beats: int,
        backend: str,
        phrase_idx: int = -1,
        phrase_label: str = "",
    ) -> int:
        """Register a new render as in-progress. Returns render ID."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            # Upsert — update if exists
            conn.execute("""
                INSERT INTO renders
                    (render_hash, audio_hash, audio_path, track_name, style, quality,
                     width, height, fps, loop_beats, backend, phrase_idx, phrase_label,
                     status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'in_progress', ?)
                ON CONFLICT(render_hash) DO UPDATE SET
                    status = 'in_progress',
                    started_at = ?,
                    error_message = NULL
            """, (render_hash, audio_hash, audio_path, track_name, style, quality,
                  width, height, fps, loop_beats, backend, phrase_idx, phrase_label,
                  now, now))

            row = conn.execute(
                "SELECT id FROM renders WHERE render_hash = ?", (render_hash,)
            ).fetchone()
            return row[0]

    def complete_render(
        self,
        render_hash: str,
        output_path: str,
        cost_usd: float = 0,
        api_calls: int = 0,
        cache_hits: int = 0,
        metadata: Optional[dict] = None,
    ):
        """Mark a render as completed."""
        now = datetime.now().isoformat()
        output_size = Path(output_path).stat().st_size if Path(output_path).exists() else 0

        with self._conn() as conn:
            conn.execute("""
                UPDATE renders SET
                    status = 'completed',
                    output_path = ?,
                    output_size = ?,
                    cost_usd = ?,
                    api_calls = ?,
                    cache_hits = ?,
                    completed_at = ?,
                    metadata_json = ?
                WHERE render_hash = ?
            """, (output_path, output_size, cost_usd, api_calls, cache_hits,
                  now, json.dumps(metadata or {}), render_hash))

    def fail_render(self, render_hash: str, error: str):
        """Mark a render as failed."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                UPDATE renders SET
                    status = 'failed',
                    completed_at = ?,
                    error_message = ?
                WHERE render_hash = ?
            """, (now, error, render_hash))

    # ── Track-level tracking ──

    def start_track(
        self,
        audio_hash: str,
        audio_path: str,
        track_name: str,
        style: str,
        quality: str,
        total_phrases: int,
        output_dir: str,
        config: Optional[dict] = None,
    ):
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO track_renders
                    (audio_hash, audio_path, track_name, style, quality,
                     total_phrases, status, started_at, output_dir, config_json)
                VALUES (?, ?, ?, ?, ?, ?, 'in_progress', ?, ?, ?)
                ON CONFLICT(audio_hash, style, quality) DO UPDATE SET
                    status = 'in_progress',
                    total_phrases = ?,
                    started_at = ?,
                    output_dir = ?
            """, (audio_hash, audio_path, track_name, style, quality,
                  total_phrases, now, output_dir, json.dumps(config or {}),
                  total_phrases, now, output_dir))

    def update_track_progress(self, audio_hash: str, style: str, quality: str,
                               completed_phrases: int, cost: float):
        with self._conn() as conn:
            conn.execute("""
                UPDATE track_renders SET
                    completed_phrases = ?,
                    total_cost = ?
                WHERE audio_hash = ? AND style = ? AND quality = ?
            """, (completed_phrases, cost, audio_hash, style, quality))

    def complete_track(self, audio_hash: str, style: str, quality: str):
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                UPDATE track_renders SET
                    status = 'completed',
                    completed_at = ?
                WHERE audio_hash = ? AND style = ? AND quality = ?
            """, (now, audio_hash, style, quality))

    # ── Query methods ──

    def get_all_renders(self, status: Optional[str] = None) -> list[dict]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM renders WHERE status = ? ORDER BY started_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM renders ORDER BY started_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_track_renders(self, status: Optional[str] = None) -> list[dict]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM track_renders WHERE status = ? ORDER BY started_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM track_renders ORDER BY started_at DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def get_render_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM renders").fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM renders WHERE status = 'completed'").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM renders WHERE status = 'failed'").fetchone()[0]
            in_progress = conn.execute("SELECT COUNT(*) FROM renders WHERE status = 'in_progress'").fetchone()[0]
            total_cost = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM renders").fetchone()[0]
            total_size = conn.execute("SELECT COALESCE(SUM(output_size), 0) FROM renders WHERE status = 'completed'").fetchone()[0]
            cache_hits = conn.execute("SELECT COUNT(*) FROM renders WHERE cache_hits > 0").fetchone()[0]

            # Unique tracks
            unique_tracks = conn.execute("SELECT COUNT(DISTINCT track_name) FROM renders").fetchone()[0]

            return {
                "total_renders": total,
                "completed": completed,
                "failed": failed,
                "in_progress": in_progress,
                "total_cost_usd": float(total_cost),
                "total_output_size_mb": float(total_size) / (1024 * 1024),
                "unique_tracks": unique_tracks,
                "cache_hit_renders": cache_hits,
            }

    def get_renders_for_track(self, track_name: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM renders WHERE track_name = ? ORDER BY phrase_idx",
                (track_name,),
            ).fetchall()
            return [dict(r) for r in rows]

    def invalidate_style(self, style: str):
        """Invalidate all renders for a style (e.g., when style YAML changes)."""
        with self._conn() as conn:
            count = conn.execute(
                "UPDATE renders SET status = 'invalidated' WHERE style = ? AND status = 'completed'",
                (style,),
            ).rowcount
            logger.info(f"Invalidated {count} renders for style '{style}'")
            return count
