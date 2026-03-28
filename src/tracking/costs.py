"""
API cost tracking — logs every API call with model, cost, and metadata.
Persistent SQLite storage. Budget limits with warnings.
"""
import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Known pricing per API call (USD)
PRICING = {
    # OpenAI DALL-E 3
    "dall-e-3:hd:1792x1024": 0.080,
    "dall-e-3:standard:1792x1024": 0.040,
    "dall-e-3:hd:1024x1024": 0.080,
    "dall-e-3:standard:1024x1024": 0.040,
    # Replicate models (approximate per-run)
    "replicate:flux-schnell": 0.003,
    "replicate:flux-pro": 0.055,
    "replicate:sdxl": 0.004,
    # OpenAI Batch API (50% discount)
    "dall-e-3:hd:1792x1024:batch": 0.040,
    "dall-e-3:standard:1792x1024:batch": 0.020,
}

DEFAULT_DB_PATH = Path.home() / ".rsv" / "costs.db"


@dataclass
class CostEntry:
    id: int
    timestamp: str
    model: str
    cost_usd: float
    track_name: str
    phrase_idx: int
    phrase_label: str
    style: str
    backend: str
    cached: bool
    metadata: dict


class CostTracker:
    """Track API costs across all generation runs."""

    def __init__(self, db_path: Optional[Path] = None, budget_limit: Optional[float] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.budget_limit = budget_limit
        self._init_db()
        self._session_cost = 0.0
        self._session_calls = 0
        self._session_cache_hits = 0

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    model TEXT NOT NULL,
                    cost_usd REAL NOT NULL,
                    track_name TEXT,
                    phrase_idx INTEGER,
                    phrase_label TEXT,
                    style TEXT,
                    backend TEXT,
                    cached INTEGER DEFAULT 0,
                    quality TEXT,
                    width INTEGER,
                    height INTEGER,
                    metadata_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS budget_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    total_cost REAL,
                    limit_usd REAL,
                    message TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON api_calls(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_track ON api_calls(track_name)
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

    def log_call(
        self,
        model: str,
        track_name: str = "",
        phrase_idx: int = -1,
        phrase_label: str = "",
        style: str = "",
        backend: str = "",
        cached: bool = False,
        quality: str = "",
        width: int = 0,
        height: int = 0,
        metadata: Optional[dict] = None,
    ) -> float:
        """
        Log an API call and return its cost.
        Cached calls are logged at $0 cost.
        """
        if cached:
            cost = 0.0
            self._session_cache_hits += 1
        else:
            cost = self._lookup_cost(model, quality)

        now = datetime.now().isoformat()

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO api_calls
                   (timestamp, model, cost_usd, track_name, phrase_idx, phrase_label,
                    style, backend, cached, quality, width, height, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, model, cost, track_name, phrase_idx, phrase_label,
                 style, backend, int(cached), quality, width, height,
                 json.dumps(metadata or {})),
            )

        self._session_cost += cost
        self._session_calls += 1

        # Budget check
        if self.budget_limit and not cached:
            total = self.get_total_cost()
            if total >= self.budget_limit:
                self._log_budget_alert(total)
                raise BudgetExceededError(
                    f"Budget limit ${self.budget_limit:.2f} exceeded "
                    f"(total: ${total:.2f})"
                )
            elif total >= self.budget_limit * 0.8:
                logger.warning(
                    f"Budget warning: ${total:.2f} / ${self.budget_limit:.2f} "
                    f"({total/self.budget_limit*100:.0f}%)"
                )

        return cost

    def _lookup_cost(self, model: str, quality: str) -> float:
        """Look up cost for a model+quality combo."""
        # Try exact match first
        key = f"{model}:{quality}"
        if key in PRICING:
            return PRICING[key]
        # Try model only
        if model in PRICING:
            return PRICING[model]
        # Try partial match
        for k, v in PRICING.items():
            if model in k:
                return v
        # Unknown model — log warning and estimate
        logger.warning(f"Unknown model cost: {model}:{quality}, estimating $0.05")
        return 0.05

    def _log_budget_alert(self, total: float):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO budget_alerts (timestamp, total_cost, limit_usd, message) VALUES (?, ?, ?, ?)",
                (datetime.now().isoformat(), total, self.budget_limit,
                 f"Budget exceeded: ${total:.2f} / ${self.budget_limit:.2f}"),
            )

    # ── Query methods ──

    def get_total_cost(self, since: Optional[str] = None) -> float:
        """Total cost, optionally since a date (ISO format)."""
        with self._conn() as conn:
            if since:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM api_calls WHERE timestamp >= ?",
                    (since,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM api_calls"
                ).fetchone()
            return float(row[0])

    def get_total_calls(self, since: Optional[str] = None) -> int:
        with self._conn() as conn:
            if since:
                row = conn.execute(
                    "SELECT COUNT(*) FROM api_calls WHERE timestamp >= ? AND cached = 0",
                    (since,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM api_calls WHERE cached = 0"
                ).fetchone()
            return int(row[0])

    def get_cache_hit_rate(self) -> float:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
            cached = conn.execute("SELECT COUNT(*) FROM api_calls WHERE cached = 1").fetchone()[0]
            if total == 0:
                return 0.0
            return cached / total

    def get_cost_by_track(self) -> list[dict]:
        """Cost breakdown per track."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT track_name,
                       COUNT(*) as total_calls,
                       SUM(CASE WHEN cached = 0 THEN 1 ELSE 0 END) as api_calls,
                       SUM(CASE WHEN cached = 1 THEN 1 ELSE 0 END) as cache_hits,
                       SUM(cost_usd) as total_cost,
                       MIN(timestamp) as first_call,
                       MAX(timestamp) as last_call
                FROM api_calls
                GROUP BY track_name
                ORDER BY total_cost DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def get_cost_by_style(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT style,
                       COUNT(*) as calls,
                       SUM(cost_usd) as total_cost
                FROM api_calls
                WHERE cached = 0
                GROUP BY style
                ORDER BY total_cost DESC
            """).fetchall()
            return [dict(r) for r in rows]

    def get_cost_by_day(self, days: int = 30) -> list[dict]:
        since = (datetime.now() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT DATE(timestamp) as day,
                       COUNT(*) as calls,
                       SUM(cost_usd) as cost
                FROM api_calls
                WHERE timestamp >= ? AND cached = 0
                GROUP BY DATE(timestamp)
                ORDER BY day DESC
            """, (since,)).fetchall()
            return [dict(r) for r in rows]

    def get_recent_calls(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM api_calls
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_session_summary(self) -> dict:
        return {
            "session_calls": self._session_calls,
            "session_api_calls": self._session_calls - self._session_cache_hits,
            "session_cache_hits": self._session_cache_hits,
            "session_cost": self._session_cost,
            "cache_hit_rate": (self._session_cache_hits / self._session_calls * 100
                               if self._session_calls > 0 else 0),
        }

    def export_json(self, path: Optional[Path] = None) -> dict:
        """Export full cost report as JSON."""
        report = {
            "generated_at": datetime.now().isoformat(),
            "total_cost": self.get_total_cost(),
            "total_api_calls": self.get_total_calls(),
            "cache_hit_rate": self.get_cache_hit_rate(),
            "by_track": self.get_cost_by_track(),
            "by_style": self.get_cost_by_style(),
            "by_day": self.get_cost_by_day(),
        }
        if path:
            path.write_text(json.dumps(report, indent=2))
        return report


class BudgetExceededError(Exception):
    """Raised when API cost exceeds the configured budget limit."""
    pass
