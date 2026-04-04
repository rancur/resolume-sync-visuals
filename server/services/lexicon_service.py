"""
Lexicon service — wraps LexiconClient with caching and NAS status joins.
"""
import logging
import time
from typing import Optional

from src.lexicon import LexiconClient
from src.nas import NASManager

from ..config import get_settings

logger = logging.getLogger(__name__)

_CACHE_TTL = 60  # seconds


class LexiconService:
    """Cached wrapper around LexiconClient + NAS status."""

    def __init__(self):
        settings = get_settings()
        self._client = LexiconClient(
            host=settings.lexicon_host,
            port=settings.lexicon_port,
        )
        self._nas = NASManager(
            nas_host=settings.nas_host,
            nas_port=settings.nas_ssh_port,
            nas_user=settings.nas_user,
            ssh_key=settings.nas_ssh_key,
        )
        self._track_cache: list[dict] | None = None
        self._cache_time: float = 0.0
        self._playlist_cache: list[dict] | None = None
        self._playlist_cache_time: float = 0.0

    def _refresh_if_stale(self):
        if self._track_cache is None or (time.time() - self._cache_time) > _CACHE_TTL:
            # Always load full library — partial loads show wrong track count
            self._track_cache = self._client.get_all_tracks()
            self._cache_time = time.time()
            self._full_cache_loaded = True

    def _ensure_full_cache(self):
        """Ensure full library is cached."""
        if getattr(self, '_full_cache_loaded', False):
            return
        self._refresh_if_stale()

    def invalidate_cache(self):
        self._track_cache = None
        self._playlist_cache = None

    def get_genres(self) -> list[str]:
        """Return all unique genres across the full library."""
        self._ensure_full_cache()
        genres = set()
        for t in (self._track_cache or []):
            g = t.get("genre")
            if g:
                genres.add(g)
        return sorted(genres)

    def get_tracks(
        self,
        search: str = "",
        sort_by: str = "title",
        sort_desc: bool = False,
        genre: str = "",
        has_video: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
        check_nas: bool = False,
    ) -> dict:
        """Return paginated track list.

        Fast by default — skips NAS video status checks.
        Pass check_nas=True to include video status (slower).
        """
        # For search or genre filter, we need the full cache
        if search or genre:
            self._ensure_full_cache()
        else:
            self._refresh_if_stale()

        tracks = list(self._track_cache or [])

        # Search filter
        if search:
            q = search.lower()
            tracks = [
                t for t in tracks
                if q in (t.get("title") or "").lower()
                or q in (t.get("artist") or "").lower()
                or q in (t.get("genre") or "").lower()
            ]

        # Genre filter
        if genre:
            tracks = [t for t in tracks if (t.get("genre") or "") == genre]

        # Sort
        def sort_key(t):
            val = t.get(sort_by, "")
            if val is None:
                return ""
            return val

        tracks.sort(key=sort_key, reverse=sort_desc)

        total = len(tracks)
        page = tracks[offset : offset + limit]

        # Optionally enrich with NAS video status (expensive — SSH per track)
        if check_nas:
            for t in page:
                title = t.get("title", "")
                try:
                    t["has_video"] = self._nas.track_has_video(title)
                except Exception:
                    t["has_video"] = False
        else:
            # Default to unknown — frontend shows neutral badge
            for t in page:
                t.setdefault("has_video", None)

        return {
            "tracks": page,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def get_track(self, track_id: str) -> Optional[dict]:
        self._refresh_if_stale()
        for t in (self._track_cache or []):
            if str(t.get("id")) == str(track_id):
                title = t.get("title", "")
                t_copy = dict(t)
                try:
                    t_copy["has_video"] = self._nas.track_has_video(title)
                    t_copy["nas_info"] = self._nas.get_track_info(title)
                except Exception:
                    t_copy["has_video"] = False
                    t_copy["nas_info"] = {}
                return t_copy
        return None

    def get_playlists(self) -> list[dict]:
        if self._playlist_cache is None or (
            time.time() - self._playlist_cache_time
        ) > _CACHE_TTL:
            self._playlist_cache = self._client.get_playlists()
            self._playlist_cache_time = time.time()
        return self._playlist_cache or []

    def get_playlist_tracks(self, playlist_id: int) -> list[dict]:
        return self._client.get_playlist_tracks(playlist_id)

    def test_connection(self) -> dict:
        return self._client.test_connection()


# Singleton
_service: LexiconService | None = None


def get_lexicon_service() -> LexiconService:
    global _service
    if _service is None:
        _service = LexiconService()
    return _service
