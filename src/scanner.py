"""
NAS Music Library Scanner.

Reads music file metadata (ID3, FLAC, etc.) for BPM/genre/key detection.
Also reads Denon Engine DJ and Pioneer Rekordbox databases.
"""
import logging
import os
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".wav", ".aif", ".aiff", ".ogg", ".m4a", ".mp4"}


def read_track_metadata(file_path: str) -> dict:
    """Read metadata from a single track file.

    Returns dict with: path, title, artist, album, bpm, genre, key, duration, format, size.
    Missing fields are None.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    result = {
        "path": str(path.resolve()),
        "title": None,
        "artist": None,
        "album": None,
        "bpm": None,
        "genre": None,
        "key": None,
        "duration": None,
        "format": path.suffix.lstrip(".").upper(),
        "size": path.stat().st_size,
    }

    try:
        audio = mutagen.File(str(path))
    except Exception as e:
        logger.warning(f"Could not read metadata from {path.name}: {e}")
        return result

    if audio is None:
        logger.warning(f"Unsupported format or no metadata: {path.name}")
        return result

    # Duration from mutagen info
    if hasattr(audio, "info") and hasattr(audio.info, "length"):
        result["duration"] = float(audio.info.length)

    # Extract tags based on file type
    if isinstance(audio, MP3):
        result.update(_read_id3_tags(audio))
    elif isinstance(audio, FLAC):
        result.update(_read_vorbis_tags(audio))
    elif isinstance(audio, OggVorbis):
        result.update(_read_vorbis_tags(audio))
    elif isinstance(audio, MP4):
        result.update(_read_mp4_tags(audio))
    else:
        # Try EasyID3-style access for other formats
        result.update(_read_generic_tags(audio))

    return result


def _read_id3_tags(audio: MP3) -> dict:
    """Extract metadata from ID3 tags (MP3)."""
    tags = {}
    try:
        easy = EasyID3(audio.filename)
    except Exception:
        easy = {}

    tags["title"] = _first(easy.get("title"))
    tags["artist"] = _first(easy.get("artist"))
    tags["album"] = _first(easy.get("album"))
    tags["genre"] = _first(easy.get("genre"))

    # BPM — stored in TBPM frame
    bpm_str = _first(easy.get("bpm"))
    if bpm_str:
        try:
            tags["bpm"] = float(bpm_str)
        except ValueError:
            pass

    # Key — stored in TKEY frame (EasyID3 doesn't expose it, check raw)
    if audio.tags:
        tkey = audio.tags.get("TKEY")
        if tkey:
            tags["key"] = str(tkey)

    return {k: v for k, v in tags.items() if v is not None}


def _read_vorbis_tags(audio) -> dict:
    """Extract metadata from Vorbis comments (FLAC, OGG)."""
    tags = {}
    if not audio.tags:
        return tags

    t = audio.tags
    tags["title"] = _first(t.get("title"))
    tags["artist"] = _first(t.get("artist"))
    tags["album"] = _first(t.get("album"))
    tags["genre"] = _first(t.get("genre"))

    # BPM
    bpm_str = _first(t.get("bpm")) or _first(t.get("TBPM"))
    if bpm_str:
        try:
            tags["bpm"] = float(bpm_str)
        except ValueError:
            pass

    # Key
    key = _first(t.get("key")) or _first(t.get("initialkey")) or _first(t.get("TKEY"))
    if key:
        tags["key"] = key

    return {k: v for k, v in tags.items() if v is not None}


def _read_mp4_tags(audio: MP4) -> dict:
    """Extract metadata from MP4/M4A tags."""
    tags = {}
    t = audio.tags or {}

    tags["title"] = _first(t.get("\xa9nam"))
    tags["artist"] = _first(t.get("\xa9ART"))
    tags["album"] = _first(t.get("\xa9alb"))
    tags["genre"] = _first(t.get("\xa9gen"))

    # BPM — stored in tmpo atom
    bpm_vals = t.get("tmpo")
    if bpm_vals:
        try:
            tags["bpm"] = float(bpm_vals[0])
        except (ValueError, IndexError):
            pass

    return {k: v for k, v in tags.items() if v is not None}


def _read_generic_tags(audio) -> dict:
    """Fallback tag reader using mutagen's generic interface."""
    tags = {}
    if not audio.tags:
        return tags

    tag_map = {
        "title": ["title", "TIT2", "\xa9nam"],
        "artist": ["artist", "TPE1", "\xa9ART"],
        "album": ["album", "TALB", "\xa9alb"],
        "genre": ["genre", "TCON", "\xa9gen"],
        "bpm": ["bpm", "TBPM", "tmpo"],
        "key": ["key", "TKEY", "initialkey"],
    }

    for field, keys in tag_map.items():
        for key in keys:
            val = audio.tags.get(key)
            if val:
                if isinstance(val, list):
                    val = str(val[0])
                else:
                    val = str(val)
                if field == "bpm":
                    try:
                        tags[field] = float(val)
                    except ValueError:
                        pass
                else:
                    tags[field] = val
                break

    return {k: v for k, v in tags.items() if v is not None}


def _first(val) -> Optional[str]:
    """Extract first item from a tag value list, or return None."""
    if val is None:
        return None
    if isinstance(val, list):
        return str(val[0]) if val else None
    return str(val)


def scan_library(directory: str, recursive: bool = True) -> list[dict]:
    """Scan a music directory and extract metadata from tags.

    Returns list of: {path, title, artist, album, bpm, genre, key, duration, format, size}
    Uses ID3 tags (MP3), FLAC tags, etc. via mutagen.
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    results = []
    glob_fn = dir_path.rglob if recursive else dir_path.glob

    for ext in SUPPORTED_EXTENSIONS:
        for file_path in sorted(glob_fn(f"*{ext}")):
            try:
                metadata = read_track_metadata(str(file_path))
                results.append(metadata)
            except Exception as e:
                logger.warning(f"Skipping {file_path.name}: {e}")

    # Sort by path
    results.sort(key=lambda r: r["path"])
    return results


def read_engine_db(db_path: str) -> list[dict]:
    """Read Denon Engine DJ SQLite database for track analysis data.

    Engine DJ stores BPM, key, waveform analysis, cue points in a SQLite DB
    (typically at: Engine Library/Database2/m.db).

    Returns list of dicts with: path, title, artist, album, bpm, key, rating.
    """
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"Engine DJ database not found: {db_path}")

    results = []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row

    try:
        # Engine DJ schema: Track table has the main metadata
        cursor = conn.execute("""
            SELECT
                t.path,
                t.filename,
                t.title,
                t.artist,
                t.album,
                t.genre,
                t.bpmAnalyzed AS bpm,
                t.keyText AS key_text,
                t.rating,
                t.length
            FROM Track t
            ORDER BY t.path
        """)

        for row in cursor:
            result = {
                "path": row["path"] or "",
                "title": row["title"] or row["filename"],
                "artist": row["artist"],
                "album": row["album"],
                "genre": row["genre"],
                "bpm": float(row["bpm"]) if row["bpm"] else None,
                "key": row["key_text"],
                "rating": row["rating"],
                "duration": float(row["length"]) if row["length"] else None,
                "source": "engine_dj",
            }
            results.append(result)

    except sqlite3.OperationalError as e:
        logger.error(f"Engine DJ database query failed: {e}")
        raise
    finally:
        conn.close()

    return results


def read_rekordbox_xml(xml_path: str) -> list[dict]:
    """Read Pioneer Rekordbox XML export for track metadata.

    Rekordbox exports track data as XML including BPM, key, rating, cue points.
    Export via: File > Export Collection in xml format.

    Returns list of dicts with: path, title, artist, album, bpm, genre, key, rating, duration.
    """
    path = Path(xml_path)
    if not path.exists():
        raise FileNotFoundError(f"Rekordbox XML not found: {xml_path}")

    results = []
    tree = ET.parse(str(path))
    root = tree.getroot()

    # Rekordbox XML structure: DJ_PLAYLISTS > COLLECTION > TRACK
    collection = root.find(".//COLLECTION")
    if collection is None:
        logger.warning("No COLLECTION element found in Rekordbox XML")
        return results

    for track in collection.findall("TRACK"):
        attrib = track.attrib
        bpm_str = attrib.get("AverageBpm") or attrib.get("BPM")
        bpm = None
        if bpm_str:
            try:
                bpm = float(bpm_str)
            except ValueError:
                pass

        duration = None
        dur_str = attrib.get("TotalTime")
        if dur_str:
            try:
                duration = float(dur_str)
            except ValueError:
                pass

        result = {
            "path": attrib.get("Location", ""),
            "title": attrib.get("Name"),
            "artist": attrib.get("Artist"),
            "album": attrib.get("Album"),
            "genre": attrib.get("Genre"),
            "bpm": bpm,
            "key": attrib.get("Tonality"),
            "rating": attrib.get("Rating"),
            "duration": duration,
            "source": "rekordbox",
        }
        results.append(result)

    return results


def read_bpm_from_tags(file_path: str) -> Optional[float]:
    """Quick BPM lookup from file tags. Returns None if not found.

    This is used by the analyzer to prefer tag BPM over librosa detection,
    since DJs manually verify BPM values.
    """
    try:
        meta = read_track_metadata(file_path)
        return meta.get("bpm")
    except Exception:
        return None
