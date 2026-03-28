"""
Lexicon DJ integration.

Connects to Lexicon's local REST API to pull track metadata, playlists,
and file paths. Uses DJ-verified BPM, key, genre, energy, and happiness
for more accurate visual generation.

API: http://<host>:48624/v1/
Requires: Lexicon running with API enabled in Settings > Integrations.
"""
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
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

# NAS connection details
NAS_HOST = "192.168.1.221"
NAS_SSH_PORT = 7844
NAS_USER = "willcurran"
NAS_SSH_KEY = Path.home() / ".ssh" / "openclaw_rpi_ed25519"

# VJ content output on NAS
NAS_VJ_CONTENT_PREFIX = "/volume1/vj-content/"
# VJ content as mounted on the M4 Mac (for Resolume source paths)
LOCAL_VJ_MOUNT = Path("/Volumes/vj-content/")


@dataclass
class VideoGenerationConfig:
    """Configuration for the Lexicon-to-Resolume video generation pipeline."""
    width: int = 1920
    height: int = 1080
    fps: int = 30
    style_name: str = "abstract"
    backend: str = "openai"
    quality: str = "high"
    video_model: str = None
    # DXV encoding for Resolume
    encode_dxv: bool = True
    # Skip tracks that already have generated videos on NAS
    skip_existing: bool = True


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


def sanitize_track_dirname(title: str) -> str:
    """Convert track title to a safe directory name."""
    name = title.lower()
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s]+', '_', name).strip('_')
    return name


def nas_ssh_cmd(remote_cmd: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    """Run a command on the NAS via SSH."""
    ssh_args = [
        "ssh",
        "-p", str(NAS_SSH_PORT),
        "-i", str(NAS_SSH_KEY),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{NAS_USER}@{NAS_HOST}",
        remote_cmd,
    ]
    return subprocess.run(ssh_args, capture_output=True, timeout=timeout)


def copy_from_nas(nas_path: str, local_path: Path) -> Path:
    """
    Copy a file from NAS to local path via SSH cat (scp not available on NAS).
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = f'cat "{nas_path}"'
    ssh_args = [
        "ssh",
        "-p", str(NAS_SSH_PORT),
        "-i", str(NAS_SSH_KEY),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{NAS_USER}@{NAS_HOST}",
        cmd,
    ]
    with open(local_path, "wb") as f:
        result = subprocess.run(ssh_args, stdout=f, stderr=subprocess.PIPE, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to copy from NAS: {nas_path}\n"
            f"stderr: {result.stderr.decode(errors='replace')}"
        )
    if not local_path.exists() or local_path.stat().st_size == 0:
        raise RuntimeError(f"File copy produced empty result: {local_path}")
    logger.info(f"Copied from NAS: {nas_path} -> {local_path} ({local_path.stat().st_size} bytes)")
    return local_path


def push_to_nas(local_path: Path, nas_path: str) -> str:
    """
    Push a file to NAS via SSH cat (scp not available on NAS).
    """
    # Ensure remote directory exists
    remote_dir = str(Path(nas_path).parent)
    nas_ssh_cmd(f'mkdir -p "{remote_dir}"')

    cmd = f'cat > "{nas_path}"'
    ssh_args = [
        "ssh",
        "-p", str(NAS_SSH_PORT),
        "-i", str(NAS_SSH_KEY),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{NAS_USER}@{NAS_HOST}",
        cmd,
    ]
    with open(local_path, "rb") as f:
        result = subprocess.run(ssh_args, stdin=f, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to push to NAS: {nas_path}\n"
            f"stderr: {result.stderr.decode(errors='replace')}"
        )
    logger.info(f"Pushed to NAS: {local_path} -> {nas_path}")
    return nas_path


def nas_file_exists(nas_path: str) -> bool:
    """Check if a file exists on NAS."""
    result = nas_ssh_cmd(f'test -f "{nas_path}" && echo EXISTS')
    return result.returncode == 0 and b"EXISTS" in result.stdout


def encode_dxv(input_path: Path, output_path: Path) -> Path:
    """
    Encode video to DXV3 codec using ffmpeg for Resolume Arena.
    Falls back to ProRes if DXV codec is not available.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Try DXV first (requires Resolume's codec pack)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-c:v", "hap",  # HAP is the open codec Resolume supports natively
        "-format", "hap_q",  # HAP Q for quality
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)

    if result.returncode != 0:
        # Fall back to ProRes which Resolume also handles well
        logger.warning("HAP encoding failed, falling back to ProRes 422")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-c:v", "prores_ks",
            "-profile:v", "2",  # ProRes 422 Normal
            "-pix_fmt", "yuv422p10le",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(
                f"Video encoding failed: {result.stderr.decode(errors='replace')}"
            )

    logger.info(f"Encoded: {input_path} -> {output_path} ({output_path.stat().st_size} bytes)")
    return output_path


def generate_video_for_track(
    track: dict,
    output_dir: Path,
    config: VideoGenerationConfig,
) -> Path:
    """Full pipeline for one track:
    1. Convert Lexicon path to NAS path
    2. Copy audio from NAS to local temp
    3. Analyze (using Lexicon BPM, not librosa)
    4. Mood analysis
    5. Generate full-song video
    6. Encode to DXV (HAP/ProRes for Resolume)
    7. Name to match ID3 title
    8. Push to NAS vj-content folder
    Returns path to final video on NAS.
    """
    title = track.get("title", "Unknown")
    artist = track.get("artist", "Unknown")
    bpm = track.get("bpm")
    location = track.get("location", "")
    track_dirname = sanitize_track_dirname(title)

    logger.info(f"Generating video for: {artist} - {title} ({bpm} BPM)")

    # Check if already exists on NAS
    nas_output_dir = f"{NAS_VJ_CONTENT_PREFIX}{track_dirname}/"
    nas_final = f"{nas_output_dir}{title}.mov"
    if config.skip_existing and nas_file_exists(nas_final):
        logger.info(f"Skipping (exists on NAS): {nas_final}")
        return Path(nas_final)

    # 1. Convert path
    nas_audio_path = lexicon_to_nas_path(location)
    logger.info(f"NAS audio path: {nas_audio_path}")

    # 2. Copy audio from NAS to local temp
    audio_ext = Path(location).suffix or ".flac"
    local_audio = output_dir / track_dirname / f"audio{audio_ext}"
    local_audio.parent.mkdir(parents=True, exist_ok=True)
    copy_from_nas(nas_audio_path, local_audio)

    # 3. Analyze (using Lexicon BPM override)
    from .analyzer.audio import analyze_track
    overrides = lexicon_track_to_analysis_overrides(track)
    analysis = analyze_track(
        local_audio,
        bpm_override=overrides.get("bpm"),
    )
    # Apply Lexicon metadata to analysis
    analysis.key = overrides.get("key", "")
    analysis.genre_hint = overrides.get("genre", "")
    analysis_dict = analysis.to_dict()

    # 4. Mood analysis
    try:
        from .analyzer.mood import analyze_mood
        mood = analyze_mood(str(local_audio))
        analysis.mood = mood.to_dict()
        analysis_dict["mood"] = mood.to_dict()
        logger.info(f"  Mood: {mood.dominant_mood} ({mood.quadrant})")
    except Exception as e:
        logger.debug(f"  Mood analysis skipped: {e}")

    # 5. Generate full-song video
    from .generator.engine import GenerationConfig, generate_visuals
    from .composer.timeline import compose_timeline

    track_output = output_dir / track_dirname
    gen_config = GenerationConfig(
        width=config.width,
        height=config.height,
        fps=config.fps,
        style_name=config.style_name,
        backend=config.backend,
        quality=config.quality,
        output_dir=str(track_output / "raw"),
        cache_dir=str(track_output / ".cache"),
        video_model=config.video_model,
    )

    clips = generate_visuals(analysis_dict, gen_config)
    composition = compose_timeline(analysis_dict, clips, track_output)

    # Concatenate all clips into a single full-song video
    raw_video = track_output / f"{title}.mp4"
    _concatenate_clips(clips, raw_video)

    # 6. Encode to Resolume-compatible format
    if config.encode_dxv:
        final_video = track_output / f"{title}.mov"
        encode_dxv(raw_video, final_video)
    else:
        final_video = raw_video

    # 7. Push to NAS vj-content folder
    push_to_nas(final_video, nas_final)

    # Save metadata alongside
    meta = {
        "title": title,
        "artist": artist,
        "bpm": bpm,
        "key": overrides.get("key", ""),
        "genre": overrides.get("genre", ""),
        "nas_path": nas_final,
        "local_vj_path": str(LOCAL_VJ_MOUNT / track_dirname / f"{title}.mov"),
        "clips": len(clips),
    }
    meta_path = track_output / "track_metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    logger.info(f"Complete: {title} -> {nas_final}")
    return Path(nas_final)


def _concatenate_clips(clips: list[dict], output_path: Path):
    """Concatenate clip videos into a single full-song video using ffmpeg."""
    if not clips:
        raise ValueError("No clips to concatenate")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build ffmpeg concat file
    concat_file = output_path.parent / "concat_list.txt"
    with open(concat_file, "w") as f:
        for clip in clips:
            clip_path = clip.get("path", "")
            if clip_path and Path(clip_path).exists():
                f.write(f"file '{clip_path}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        # Retry with re-encoding if stream copy fails
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(
                f"Clip concatenation failed: {result.stderr.decode(errors='replace')}"
            )

    concat_file.unlink(missing_ok=True)
    logger.info(f"Concatenated {len(clips)} clips -> {output_path}")


def generate_show(
    client: "LexiconClient",
    output_dir: Path,
    config: VideoGenerationConfig,
    show_name: str = "Will See",
    limit: int = None,
) -> Path:
    """Generate videos for entire Lexicon library and build one Resolume composition.

    1. Pull all tracks from Lexicon API
    2. Generate video for each track
    3. Build single .avc composition file with ALL tracks
    4. Each clip in Denon transport mode, linked by track title

    Returns:
        Path to the .avc composition file.
    """
    from .resolume.show import create_denon_show_composition

    # 1. Pull all tracks
    logger.info(f"Pulling tracks from Lexicon...")
    if limit:
        tracks = client.get_tracks(limit=limit)
    else:
        tracks = client.get_all_tracks()

    logger.info(f"Found {len(tracks)} tracks")

    # 2. Generate video for each track
    generated = []
    for i, track in enumerate(tracks):
        title = track.get("title", "Unknown")
        artist = track.get("artist", "Unknown")
        logger.info(f"\n[{i+1}/{len(tracks)}] {artist} - {title}")

        try:
            nas_path = generate_video_for_track(track, output_dir, config)
            track_dirname = sanitize_track_dirname(title)
            generated.append({
                "title": title,
                "artist": artist,
                "bpm": track.get("bpm", 128.0),
                "nas_path": str(nas_path),
                "local_vj_path": str(LOCAL_VJ_MOUNT / track_dirname / f"{title}.mov"),
            })
        except Exception as e:
            logger.error(f"Failed to generate video for {title}: {e}")
            continue

    if not generated:
        raise RuntimeError("No videos were generated successfully")

    logger.info(f"\nGenerated {len(generated)} videos")

    # 3. Build .avc composition
    avc_path = output_dir / f"{show_name}.avc"
    create_denon_show_composition(generated, avc_path, show_name=show_name)

    # Also push composition to NAS
    nas_avc = f"{NAS_VJ_CONTENT_PREFIX}{show_name}.avc"
    try:
        push_to_nas(avc_path, nas_avc)
    except Exception as e:
        logger.warning(f"Failed to push .avc to NAS: {e}")

    logger.info(f"Show composition: {avc_path}")
    return avc_path


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
