"""
Bulk progress persistence — tracks bulk processing runs so interrupted runs can resume.
SQLite-backed with run-level and file-level tracking.
"""
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".rsv" / "progress.db"


class BulkProgress:
    """Track progress of bulk processing runs. SQLite-backed."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bulk_runs (
                    run_id TEXT PRIMARY KEY,
                    directory TEXT NOT NULL,
                    style TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    total_files INTEGER NOT NULL,
                    status TEXT DEFAULT 'in_progress',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bulk_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    output_dir TEXT,
                    cost REAL DEFAULT 0,
                    clips INTEGER DEFAULT 0,
                    error TEXT,
                    reason TEXT,
                    completed_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES bulk_runs(run_id),
                    UNIQUE(run_id, file_path)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bulk_run_dir
                ON bulk_runs(directory, started_at DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_bulk_files_run
                ON bulk_files(run_id, status)
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

    def start_run(self, directory: str, style: str, quality: str,
                  total_files: int) -> str:
        """Start a new bulk run. Returns run_id."""
        run_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO bulk_runs (run_id, directory, style, quality,
                                       total_files, status, started_at)
                VALUES (?, ?, ?, ?, ?, 'in_progress', ?)
            """, (run_id, directory, style, quality, total_files, now))
        return run_id

    def mark_file_complete(self, run_id: str, file_path: str,
                           output_dir: str, cost: float, clips: int):
        """Mark a file as completed in this run."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO bulk_files (run_id, file_path, status, output_dir,
                                        cost, clips, completed_at)
                VALUES (?, ?, 'completed', ?, ?, ?, ?)
                ON CONFLICT(run_id, file_path) DO UPDATE SET
                    status = 'completed',
                    output_dir = ?,
                    cost = ?,
                    clips = ?,
                    completed_at = ?
            """, (run_id, file_path, output_dir, cost, clips, now,
                  output_dir, cost, clips, now))

    def mark_file_failed(self, run_id: str, file_path: str, error: str):
        """Mark a file as failed."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO bulk_files (run_id, file_path, status, error,
                                        completed_at)
                VALUES (?, ?, 'failed', ?, ?)
                ON CONFLICT(run_id, file_path) DO UPDATE SET
                    status = 'failed',
                    error = ?,
                    completed_at = ?
            """, (run_id, file_path, error, now, error, now))

    def mark_file_skipped(self, run_id: str, file_path: str, reason: str):
        """Mark a file as skipped (already exists, etc.)."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO bulk_files (run_id, file_path, status, reason,
                                        completed_at)
                VALUES (?, ?, 'skipped', ?, ?)
                ON CONFLICT(run_id, file_path) DO UPDATE SET
                    status = 'skipped',
                    reason = ?,
                    completed_at = ?
            """, (run_id, file_path, reason, now, reason, now))

    def get_run_status(self, run_id: str) -> dict:
        """Get status: total, completed, failed, skipped, remaining files."""
        with self._conn() as conn:
            run = conn.execute(
                "SELECT * FROM bulk_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not run:
                return {}

            run_dict = dict(run)
            completed = conn.execute(
                "SELECT COUNT(*) FROM bulk_files WHERE run_id = ? AND status = 'completed'",
                (run_id,),
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM bulk_files WHERE run_id = ? AND status = 'failed'",
                (run_id,),
            ).fetchone()[0]
            skipped = conn.execute(
                "SELECT COUNT(*) FROM bulk_files WHERE run_id = ? AND status = 'skipped'",
                (run_id,),
            ).fetchone()[0]
            total_cost = conn.execute(
                "SELECT COALESCE(SUM(cost), 0) FROM bulk_files WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            total_clips = conn.execute(
                "SELECT COALESCE(SUM(clips), 0) FROM bulk_files WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]

            total = run_dict["total_files"]
            remaining = total - completed - failed - skipped

            return {
                "run_id": run_id,
                "directory": run_dict["directory"],
                "style": run_dict["style"],
                "quality": run_dict["quality"],
                "status": run_dict["status"],
                "started_at": run_dict["started_at"],
                "completed_at": run_dict["completed_at"],
                "total": total,
                "completed": completed,
                "failed": failed,
                "skipped": skipped,
                "remaining": remaining,
                "total_cost": float(total_cost),
                "total_clips": int(total_clips),
            }

    def get_incomplete_files(self, run_id: str) -> list[str]:
        """Get list of files not yet processed (for resume)."""
        with self._conn() as conn:
            # Get all files that have been processed (any status)
            processed = conn.execute(
                "SELECT file_path FROM bulk_files WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            processed_set = {row[0] for row in processed}

            # Get the run info for the directory
            run = conn.execute(
                "SELECT directory FROM bulk_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if not run:
                return []

            # Also include failed files (they should be retried)
            failed = conn.execute(
                "SELECT file_path FROM bulk_files WHERE run_id = ? AND status = 'failed'",
                (run_id,),
            ).fetchall()
            failed_set = {row[0] for row in failed}

            return sorted(failed_set)

    def get_completed_files(self, run_id: str) -> set[str]:
        """Get set of file paths that completed or were skipped."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT file_path FROM bulk_files WHERE run_id = ? AND status IN ('completed', 'skipped')",
                (run_id,),
            ).fetchall()
            return {row[0] for row in rows}

    def get_latest_run(self, directory: str) -> Optional[str]:
        """Get the latest run_id for a directory (for auto-resume)."""
        # Normalize directory path for consistent matching
        norm_dir = str(Path(directory).resolve())
        with self._conn() as conn:
            row = conn.execute("""
                SELECT run_id FROM bulk_runs
                WHERE directory = ? AND status = 'in_progress'
                ORDER BY started_at DESC
                LIMIT 1
            """, (norm_dir,)).fetchone()
            return row[0] if row else None

    def complete_run(self, run_id: str):
        """Mark entire run as complete."""
        now = datetime.now().isoformat()
        with self._conn() as conn:
            conn.execute("""
                UPDATE bulk_runs SET status = 'completed', completed_at = ?
                WHERE run_id = ?
            """, (now, run_id))
