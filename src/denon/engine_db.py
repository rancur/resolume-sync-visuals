"""
Denon Engine DJ database reader.

Engine DJ stores track analysis data in a SQLite database called `m.db`
located at the root of the Engine Library folder structure.

Database locations (Engine DJ v3+):
- USB drive: /path/to/usb/Engine Library/Database2/m.db
- macOS local: ~/Music/Engine Library/Database2/m.db
- SC6000 internal: Engine Library/Database2/m.db on the internal SSD
- Older versions: Engine Library/m.db (no Database2 subfolder)

Key tables in m.db:
- Track: id, path, filename, title, artist, album, genre, bpm, key, duration
- MetaData: textual track info (title, artist, album, genre, comments)
- MetaDataInteger: numeric data (ratings, musical key, play count)
- Crate: id, title (playlists/folders)
- CrateTrackList: crateId, trackId (playlist membership)

Performance data (p.db): beat grids, hot cues, loops, waveforms (zlib compressed)

The BPM field from Engine DJ is reliable — it's been analyzed by the
hardware and often manually verified by the DJ.

StagelinQ protocol (real-time):
- Discovery: UDP broadcast on port 51337
- Communication: TCP after discovery via StateMap service
- Data: BPM, track name, beat position, fader positions, 200+ states/deck
- Python library: PyStageLinQ (pip install PyStageLinQ)
"""
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Common Engine Library locations
ENGINE_DB_PATHS = [
    Path.home() / "Music" / "Engine Library" / "m.db",
    Path("/Volumes") / "**" / "Engine Library" / "m.db",  # USB drives on macOS
]


@contextmanager
def _open_db(db_path: Path):
    """Open Engine DJ database read-only."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def find_engine_db(search_paths: Optional[list[str]] = None) -> Optional[Path]:
    """
    Find the Engine DJ database file.
    Searches default locations and any provided paths.
    """
    paths_to_check = []

    if search_paths:
        for p in search_paths:
            p = Path(p)
            if p.name == "m.db" and p.exists():
                return p
            # Check Database2 first (Engine DJ v3+), then legacy
            for subpath in ["Database2/m.db", "m.db"]:
                db = p / subpath
                if db.exists():
                    return db
                db = p / "Engine Library" / subpath
                if db.exists():
                    return db

    # Check default locations (Database2 first for Engine DJ v3+, then legacy)
    for subpath in ["Database2/m.db", "m.db"]:
        home_db = Path.home() / "Music" / "Engine Library" / subpath
        if home_db.exists():
            return home_db

    # Check mounted volumes (USB drives)
    volumes = Path("/Volumes")
    if volumes.exists():
        for vol in volumes.iterdir():
            for subpath in ["Database2/m.db", "m.db"]:
                db = vol / "Engine Library" / subpath
                if db.exists():
                    return db

    return None


def read_engine_library(db_path: str | Path) -> list[dict]:
    """
    Read all tracks from an Engine DJ database.

    Returns list of track dicts with:
    - path, filename, title, artist, album, genre
    - bpm (float, from Engine analysis)
    - key (musical key)
    - duration (seconds)
    - rating, comment
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Engine DB not found: {db_path}")

    tracks = []

    with _open_db(db_path) as conn:
        # Check which tables exist
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        if "Track" not in tables:
            logger.warning("No Track table found in Engine DB")
            return []

        # Get column names
        columns = {row[1] for row in conn.execute("PRAGMA table_info(Track)").fetchall()}

        # Build query based on available columns
        select_fields = ["id"]
        field_map = {
            "path": "path",
            "filename": "filename",
            "title": "title",
            "artist": "artist",
            "album": "album",
            "genre": "genre",
            "comment": "comment",
            "year": "year",
            "label": "label",
            "rating": "rating",
        }

        for col, alias in field_map.items():
            if col in columns:
                select_fields.append(col)

        # BPM field (Engine uses different names in different versions)
        bpm_col = None
        for candidate in ["bpmAnalyzed", "bpm"]:
            if candidate in columns:
                bpm_col = candidate
                break

        if bpm_col:
            select_fields.append(bpm_col)

        # Key field
        key_col = None
        for candidate in ["keyText", "key", "keyAnalyzed"]:
            if candidate in columns:
                key_col = candidate
                break

        if key_col:
            select_fields.append(key_col)

        # Duration
        duration_col = None
        for candidate in ["length", "duration"]:
            if candidate in columns:
                duration_col = candidate
                break

        if duration_col:
            select_fields.append(duration_col)

        query = f"SELECT {', '.join(select_fields)} FROM Track ORDER BY title"
        rows = conn.execute(query).fetchall()

        for row in rows:
            track = dict(row)

            # Normalize field names
            if bpm_col and bpm_col in track:
                track["bpm"] = float(track.pop(bpm_col, 0) or 0)
            else:
                track["bpm"] = 0.0

            if key_col and key_col in track:
                track["key"] = str(track.pop(key_col, "") or "")
            else:
                track["key"] = ""

            if duration_col and duration_col in track:
                # Engine stores duration in various units
                raw_dur = track.pop(duration_col, 0) or 0
                # If > 1000000, it's likely in nanoseconds
                if raw_dur > 1000000:
                    track["duration"] = raw_dur / 1000000000.0
                elif raw_dur > 10000:
                    track["duration"] = raw_dur / 1000.0
                else:
                    track["duration"] = float(raw_dur)
            else:
                track["duration"] = 0.0

            tracks.append(track)

    logger.info(f"Read {len(tracks)} tracks from Engine DB: {db_path}")
    return tracks


def read_track_info(db_path: str | Path, filename: str) -> Optional[dict]:
    """
    Look up a specific track by filename in the Engine DB.
    Useful for getting the DJ-verified BPM for a file being processed.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return None

    tracks = read_engine_library(db_path)
    filename_lower = filename.lower()

    for track in tracks:
        track_filename = track.get("filename", "").lower()
        track_path = track.get("path", "").lower()
        if filename_lower in track_filename or filename_lower in track_path:
            return track

    return None


def read_crates(db_path: str | Path) -> list[dict]:
    """Read playlist/crate structure from Engine DB."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []

    crates = []

    with _open_db(db_path) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        if "Crate" not in tables:
            return []

        crate_rows = conn.execute("SELECT id, title FROM Crate ORDER BY title").fetchall()

        for crate in crate_rows:
            crate_id = crate["id"]
            title = crate["title"]

            # Get tracks in this crate
            track_ids = []
            if "CrateTrackList" in tables:
                track_rows = conn.execute(
                    "SELECT trackId FROM CrateTrackList WHERE crateId = ?",
                    (crate_id,),
                ).fetchall()
                track_ids = [r["trackId"] for r in track_rows]

            crates.append({
                "id": crate_id,
                "title": title,
                "track_count": len(track_ids),
                "track_ids": track_ids,
            })

    return crates
