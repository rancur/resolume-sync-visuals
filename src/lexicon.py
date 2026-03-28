"""
Lexicon DJ integration.

Connects to Lexicon's local REST API to pull track metadata, playlists,
and file paths. Uses DJ-verified BPM, key, genre, energy, and happiness
for more accurate visual generation.

API: http://<host>:48624/v1/
Requires: Lexicon running with API enabled in Settings > Integrations.
"""
import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_HOST = "192.168.1.116"
DEFAULT_PORT = 48624
DEFAULT_TIMEOUT = 10.0

# Path mapping: Lexicon stores paths as seen by the M4 Mac Mini
# We need to map them to NAS paths for file access
LEXICON_PATH_PREFIX = "/Volumes/Macintosh HD/Users/willcurran/SynologyDrive/Database/"
NAS_PATH_PREFIX = "/volume1/music/Database/"


class LexiconClient:
    """Client for Lexicon DJ's local REST API."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = f"http://{host}:{port}/v1"
        self.timeout = timeout

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make a GET request to the Lexicon API."""
        url = f"{self.base_url}/{endpoint}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    def test_connection(self) -> dict:
        """Test API connection. Returns first track as proof of life."""
        try:
            data = self._get("tracks", {"limit": 1, "fields": "id"})
            total = data.get("data", {}).get("total", 0)
            return {"connected": True, "total_tracks": total}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    def get_track_count(self) -> int:
        """Get total number of tracks in library."""
        data = self._get("tracks", {"limit": 1, "fields": "id"})
        return data.get("data", {}).get("total", 0)

    def get_tracks(
        self,
        limit: int = 50,
        offset: int = 0,
        fields: Optional[list[str]] = None,
    ) -> list[dict]:
        """Get tracks with metadata."""
        if fields is None:
            fields = [
                "id", "title", "artist", "bpm", "genre", "key",
                "location", "energy", "happiness", "danceability",
                "duration", "rating", "color",
            ]

        params = {"limit": limit, "offset": offset}
        for f in fields:
            params[f"fields"] = f  # Last one wins with simple params

        # Build fields properly
        url = f"{self.base_url}/tracks?limit={limit}&offset={offset}"
        for f in fields:
            url += f"&fields={f}"

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        return data.get("data", {}).get("tracks", [])

    def get_all_tracks(self, fields: Optional[list[str]] = None) -> list[dict]:
        """Get all tracks (paginated)."""
        all_tracks = []
        offset = 0
        batch_size = 100

        while True:
            tracks = self.get_tracks(limit=batch_size, offset=offset, fields=fields)
            if not tracks:
                break
            all_tracks.extend(tracks)
            offset += batch_size
            if len(tracks) < batch_size:
                break

        return all_tracks

    def search_tracks(self, query: str) -> list[dict]:
        """Search for tracks by title or artist."""
        # Lexicon API doesn't have a search endpoint per se,
        # but we can filter by fetching and matching
        all_tracks = self.get_tracks(limit=5000, fields=[
            "id", "title", "artist", "bpm", "genre", "key",
            "location", "energy", "happiness", "duration",
        ])
        query_lower = query.lower()
        return [
            t for t in all_tracks
            if query_lower in (t.get("title", "") or "").lower()
            or query_lower in (t.get("artist", "") or "").lower()
        ]

    def get_playlists(self) -> list[dict]:
        """Get all playlists."""
        data = self._get("playlists")
        return data.get("data", {}).get("playlists", [])

    def get_playlist_tracks(self, playlist_id: int) -> list[dict]:
        """Get tracks in a specific playlist."""
        data = self._get("playlist", {"id": playlist_id})
        playlist = data.get("data", {}).get("playlist", {})
        track_ids = playlist.get("trackIds", [])

        if not track_ids:
            return []

        # Fetch full track data for each ID
        # (Lexicon API doesn't have a bulk-by-ID endpoint,
        # so we fetch all and filter)
        all_tracks = self.get_tracks(limit=5000)
        id_set = set(track_ids)
        return [t for t in all_tracks if t.get("id") in id_set]


def lexicon_to_nas_path(lexicon_path: str) -> str:
    """
    Convert a Lexicon file path (M4 Mac Mini local path) to NAS path.

    Lexicon: /Volumes/Macintosh HD/Users/willcurran/SynologyDrive/Database/Artist/...
    NAS:     /volume1/music/Database/Artist/...
    """
    if lexicon_path.startswith(LEXICON_PATH_PREFIX):
        return NAS_PATH_PREFIX + lexicon_path[len(LEXICON_PATH_PREFIX):]
    return lexicon_path


def lexicon_track_to_analysis_overrides(track: dict) -> dict:
    """
    Extract analysis overrides from Lexicon track metadata.
    These override librosa's auto-detection with DJ-verified values.
    """
    overrides = {}

    bpm = track.get("bpm")
    if bpm and bpm > 0:
        # Lexicon stores DnB as half-time BPM (87.5 = 175)
        # Double it if it's clearly half-time
        if bpm < 100 and track.get("genre", "").lower() in ("drum & bass", "dnb", "jungle"):
            bpm = bpm * 2
        overrides["bpm"] = float(bpm)

    key = track.get("key")
    if key:
        overrides["key"] = key

    genre = track.get("genre")
    if genre:
        overrides["genre"] = genre

    energy = track.get("energy")
    if energy is not None:
        overrides["energy"] = energy  # 0-10 scale

    happiness = track.get("happiness")
    if happiness is not None:
        overrides["happiness"] = happiness  # 0-10 scale

    return overrides
