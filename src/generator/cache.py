"""
Smart keyframe caching to reduce regeneration cost.

Caches generated keyframes and video segments indexed by a hash of
(prompt, model, resolution, style). Cache hits skip expensive API calls.

Cache layout:
  <cache_dir>/
    cache.db          -- SQLite index
    keyframes/        -- cached keyframe images
    segments/         -- cached video segments

Cache key = SHA-256 of: prompt + model + resolution + extra_params
"""
import hashlib
import json
import logging
import shutil
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_CACHE_DIR = _PROJECT_ROOT / "output" / ".cache"


@dataclass
class CacheEntry:
    """A cached generation result."""
    cache_key: str
    entry_type: str  # "keyframe" or "segment"
    file_path: str
    prompt: str
    model: str
    resolution: str
    brand_hash: str = ""
    created_at: str = ""
    file_size: int = 0
    hit_count: int = 0
    last_hit_at: str = ""


@dataclass
class CacheStats:
    """Cache statistics."""
    total_entries: int = 0
    keyframe_entries: int = 0
    segment_entries: int = 0
    total_hits: int = 0
    total_size_bytes: int = 0
    estimated_savings: float = 0.0  # estimated $ saved from cache hits

    def to_dict(self) -> dict:
        return {
            "total_entries": self.total_entries,
            "keyframe_entries": self.keyframe_entries,
            "segment_entries": self.segment_entries,
            "total_hits": self.total_hits,
            "total_size_mb": round(self.total_size_bytes / (1024 * 1024), 2),
            "estimated_savings_usd": round(self.estimated_savings, 2),
            "hit_rate": round(self.total_hits / max(self.total_entries, 1) * 100, 1),
        }


class KeyframeCache:
    """Manages cached keyframes and video segments."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.db_path = self.cache_dir / "cache.db"
        self.keyframes_dir = self.cache_dir / "keyframes"
        self.segments_dir = self.cache_dir / "segments"

        # Create directories
        self.keyframes_dir.mkdir(parents=True, exist_ok=True)
        self.segments_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

    @contextmanager
    def _get_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._get_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_key TEXT PRIMARY KEY,
                    entry_type TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    brand_hash TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    file_size INTEGER DEFAULT 0,
                    hit_count INTEGER DEFAULT 0,
                    last_hit_at TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_type
                ON cache_entries(entry_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cache_brand
                ON cache_entries(brand_hash)
            """)

    @staticmethod
    def compute_cache_key(
        prompt: str,
        model: str = "",
        resolution: str = "",
        **extra,
    ) -> str:
        """Compute a deterministic cache key from generation parameters.

        Args:
            prompt: The generation prompt.
            model: Model name/ID.
            resolution: Resolution string (e.g., "1920x1080").
            **extra: Additional parameters to include in the hash.

        Returns:
            SHA-256 hex digest.
        """
        key_data = json.dumps(
            {"prompt": prompt, "model": model, "resolution": resolution, **extra},
            sort_keys=True,
        )
        return hashlib.sha256(key_data.encode()).hexdigest()

    @staticmethod
    def compute_brand_hash(brand_config: dict) -> str:
        """Compute a hash of a brand config for invalidation tracking."""
        # Hash the style and section prompts (not the entire config, which
        # includes metadata that doesn't affect generation)
        relevant = {
            "style": brand_config.get("style", {}),
            "sections": brand_config.get("sections", {}),
            "mood_modifiers": brand_config.get("mood_modifiers", {}),
            "genre_modifiers": brand_config.get("genre_modifiers", {}),
        }
        data = json.dumps(relevant, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def get_keyframe(
        self,
        prompt: str,
        model: str = "",
        resolution: str = "",
    ) -> Optional[Path]:
        """Look up a cached keyframe image.

        Returns the file path if cached and file exists, otherwise None.
        """
        key = self.compute_cache_key(prompt, model, resolution)
        return self._get_entry(key, "keyframe")

    def get_segment(
        self,
        prompt: str,
        model: str = "",
        resolution: str = "",
        **extra,
    ) -> Optional[Path]:
        """Look up a cached video segment."""
        key = self.compute_cache_key(prompt, model, resolution, **extra)
        return self._get_entry(key, "segment")

    def _get_entry(self, cache_key: str, entry_type: str) -> Optional[Path]:
        """Internal: look up and validate a cache entry."""
        with self._get_db() as conn:
            row = conn.execute(
                "SELECT * FROM cache_entries WHERE cache_key = ? AND entry_type = ?",
                (cache_key, entry_type),
            ).fetchone()

            if not row:
                return None

            file_path = Path(row["file_path"])
            if not file_path.exists():
                # File was deleted, remove stale entry
                conn.execute(
                    "DELETE FROM cache_entries WHERE cache_key = ?",
                    (cache_key,),
                )
                logger.debug(f"Cache miss (stale): {cache_key[:12]}...")
                return None

            # Update hit count
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            conn.execute(
                "UPDATE cache_entries SET hit_count = hit_count + 1, last_hit_at = ? "
                "WHERE cache_key = ?",
                (now, cache_key),
            )

            logger.info(f"Cache hit ({entry_type}): {cache_key[:12]}...")
            return file_path

    def put_keyframe(
        self,
        prompt: str,
        file_path: Path,
        model: str = "",
        resolution: str = "",
        brand_hash: str = "",
    ) -> str:
        """Store a keyframe image in the cache.

        Copies the file to cache storage and creates an index entry.

        Returns:
            Cache key.
        """
        key = self.compute_cache_key(prompt, model, resolution)
        return self._put_entry(key, "keyframe", file_path, prompt, model,
                               resolution, brand_hash)

    def put_segment(
        self,
        prompt: str,
        file_path: Path,
        model: str = "",
        resolution: str = "",
        brand_hash: str = "",
        **extra,
    ) -> str:
        """Store a video segment in the cache."""
        key = self.compute_cache_key(prompt, model, resolution, **extra)
        return self._put_entry(key, "segment", file_path, prompt, model,
                               resolution, brand_hash)

    def _put_entry(
        self,
        cache_key: str,
        entry_type: str,
        source_path: Path,
        prompt: str,
        model: str,
        resolution: str,
        brand_hash: str,
    ) -> str:
        """Internal: store a file in the cache."""
        source_path = Path(source_path)
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        # Copy to cache directory
        storage_dir = self.keyframes_dir if entry_type == "keyframe" else self.segments_dir
        ext = source_path.suffix
        cache_file = storage_dir / f"{cache_key[:24]}{ext}"
        shutil.copy2(str(source_path), str(cache_file))

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        file_size = cache_file.stat().st_size

        with self._get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO cache_entries
                   (cache_key, entry_type, file_path, prompt, model, resolution,
                    brand_hash, created_at, file_size, hit_count, last_hit_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '')""",
                (cache_key, entry_type, str(cache_file), prompt, model,
                 resolution, brand_hash, now, file_size),
            )

        logger.info(f"Cached {entry_type}: {cache_key[:12]}... ({file_size // 1024}KB)")
        return cache_key

    def invalidate_brand(self, brand_hash: str) -> int:
        """Invalidate all cache entries for a specific brand hash.

        Deletes cached files and index entries.

        Returns:
            Number of entries invalidated.
        """
        with self._get_db() as conn:
            rows = conn.execute(
                "SELECT file_path FROM cache_entries WHERE brand_hash = ?",
                (brand_hash,),
            ).fetchall()

            for row in rows:
                fp = Path(row["file_path"])
                if fp.exists():
                    fp.unlink()

            conn.execute(
                "DELETE FROM cache_entries WHERE brand_hash = ?",
                (brand_hash,),
            )

            count = len(rows)
            if count:
                logger.info(f"Invalidated {count} cache entries for brand {brand_hash[:8]}...")
            return count

    def clear(self, older_than_days: Optional[int] = None) -> int:
        """Clear cache entries.

        Args:
            older_than_days: If set, only clear entries older than N days.
                            If None, clear everything.

        Returns:
            Number of entries cleared.
        """
        with self._get_db() as conn:
            if older_than_days is not None:
                cutoff = time.time() - (older_than_days * 86400)
                cutoff_str = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(cutoff)
                )
                rows = conn.execute(
                    "SELECT file_path FROM cache_entries WHERE created_at < ?",
                    (cutoff_str,),
                ).fetchall()
                conn.execute(
                    "DELETE FROM cache_entries WHERE created_at < ?",
                    (cutoff_str,),
                )
            else:
                rows = conn.execute(
                    "SELECT file_path FROM cache_entries"
                ).fetchall()
                conn.execute("DELETE FROM cache_entries")

            count = 0
            for row in rows:
                fp = Path(row["file_path"])
                if fp.exists():
                    fp.unlink()
                    count += 1

            logger.info(f"Cleared {count} cache entries")
            return count

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        stats = CacheStats()

        with self._get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN entry_type='keyframe' THEN 1 ELSE 0 END) as kf, "
                "SUM(CASE WHEN entry_type='segment' THEN 1 ELSE 0 END) as seg, "
                "SUM(hit_count) as hits, "
                "SUM(file_size) as total_size "
                "FROM cache_entries"
            ).fetchone()

            stats.total_entries = row["total"] or 0
            stats.keyframe_entries = row["kf"] or 0
            stats.segment_entries = row["seg"] or 0
            stats.total_hits = row["hits"] or 0
            stats.total_size_bytes = row["total_size"] or 0

            # Estimate savings: keyframe hit ~$0.04, segment hit ~$0.50
            kf_hits = conn.execute(
                "SELECT SUM(hit_count) FROM cache_entries WHERE entry_type='keyframe'"
            ).fetchone()[0] or 0
            seg_hits = conn.execute(
                "SELECT SUM(hit_count) FROM cache_entries WHERE entry_type='segment'"
            ).fetchone()[0] or 0
            stats.estimated_savings = kf_hits * 0.04 + seg_hits * 0.50

        return stats

    def find_similar(
        self,
        prompt: str,
        threshold: float = 0.9,
        limit: int = 5,
    ) -> list[CacheEntry]:
        """Find cached entries with similar prompts.

        Uses simple word-overlap similarity (Jaccard).
        For production, replace with embedding-based cosine similarity.

        Args:
            prompt: Query prompt.
            threshold: Minimum similarity (0-1).
            limit: Max results.

        Returns:
            List of similar CacheEntry objects.
        """
        query_words = set(prompt.lower().split())
        if not query_words:
            return []

        results = []
        with self._get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM cache_entries ORDER BY created_at DESC LIMIT 500"
            ).fetchall()

            for row in rows:
                entry_words = set(row["prompt"].lower().split())
                if not entry_words:
                    continue

                # Jaccard similarity
                intersection = len(query_words & entry_words)
                union = len(query_words | entry_words)
                similarity = intersection / union if union > 0 else 0

                if similarity >= threshold:
                    results.append(CacheEntry(
                        cache_key=row["cache_key"],
                        entry_type=row["entry_type"],
                        file_path=row["file_path"],
                        prompt=row["prompt"],
                        model=row["model"],
                        resolution=row["resolution"],
                        brand_hash=row["brand_hash"],
                        created_at=row["created_at"],
                        file_size=row["file_size"],
                        hit_count=row["hit_count"],
                        last_hit_at=row["last_hit_at"],
                    ))

                    if len(results) >= limit:
                        break

        return results
