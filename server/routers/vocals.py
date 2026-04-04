"""
Vocal isolation endpoints for lyric display overlays.

Uses Demucs stem separation (already available in src/analyzer/stems.py) to
extract vocal timing information for lyric overlay synchronization.

GET /api/vocals/{track_name}/timing
    Returns vocal activity timeline — when vocals are present and their intensity.

GET /api/vocals/{track_name}/regions
    Returns discrete vocal regions with start/end times for lyric display.
"""
import logging
from typing import Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Query

from src.analyzer.stems import (
    analyze_stem,
    find_active_regions,
    STEM_NAMES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vocals", tags=["vocals"])


def _get_vocal_analysis(audio: np.ndarray, sr: int) -> dict:
    """Analyze a vocal stem and return timing information."""
    analysis = analyze_stem(audio, sr, "vocals")

    rms = analysis["rms"]
    rms_times = analysis["rms_times"]
    hop = analysis["hop_length"]

    # Get active vocal regions
    regions = find_active_regions(rms, sr, hop, threshold_factor=0.15)

    # Build per-frame energy at ~30fps for overlay
    fps = 30.0
    duration = len(audio) / sr
    total_frames = int(duration * fps)

    from src.analyzer.stems import _resample_to_fps
    energy_per_frame = _resample_to_fps(rms, rms_times, fps, total_frames)

    return {
        "duration": round(duration, 3),
        "sample_rate": sr,
        "fps": fps,
        "total_frames": total_frames,
        "energy": energy_per_frame,
        "active_regions": [
            {"start": round(s, 3), "end": round(e, 3), "duration": round(e - s, 3)}
            for s, e in regions
        ],
        "mean_energy": round(float(np.mean(rms)), 4) if len(rms) > 0 else 0,
        "max_energy": round(float(np.max(rms)), 4) if len(rms) > 0 else 0,
        "spectral_character": analysis["spectral_character"],
        "mean_centroid": round(float(analysis["mean_centroid"]), 1),
    }


@router.get("/{track_name}/timing")
async def get_vocal_timing(
    track_name: str,
    fps: float = Query(30.0, ge=1.0, le=120.0),
):
    """Return vocal activity timeline for a track.

    This endpoint requires the vocal stem to already be separated (cached on NAS
    or locally). If stems aren't available, it returns a 404 with instructions
    to run stem separation first.

    Response includes:
    - Per-frame energy values at the requested FPS
    - Active regions where vocals are present
    - Spectral characteristics of the vocal
    """
    from pathlib import Path
    from ..config import get_settings

    settings = get_settings()
    db_dir = Path(settings.db_path)

    # Check for cached vocal stem locally
    stems_dir = db_dir / "stems" / track_name
    vocal_path = stems_dir / "vocals.wav"

    if not vocal_path.exists():
        # Try NAS
        try:
            import subprocess
            nas_vocal = f"/volume1/vj-content/{track_name}/stems/vocals.wav"
            ssh_args = [
                "ssh", "-p", str(settings.nas_ssh_port),
                "-i", str(settings.nas_ssh_key),
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=10",
                f"{settings.nas_user}@{settings.nas_host}",
                f'test -f "{nas_vocal}" && echo "EXISTS"',
            ]
            result = subprocess.run(ssh_args, capture_output=True, text=True, timeout=10)
            if "EXISTS" in result.stdout:
                # Pull the vocal stem
                stems_dir.mkdir(parents=True, exist_ok=True)
                pull_args = [
                    "ssh", "-p", str(settings.nas_ssh_port),
                    "-i", str(settings.nas_ssh_key),
                    "-o", "StrictHostKeyChecking=no",
                    f"{settings.nas_user}@{settings.nas_host}",
                    f'cat "{nas_vocal}"',
                ]
                with open(vocal_path, "wb") as f:
                    proc = subprocess.run(pull_args, stdout=f, stderr=subprocess.PIPE, timeout=120)
                if proc.returncode != 0 or vocal_path.stat().st_size == 0:
                    vocal_path.unlink(missing_ok=True)
            else:
                raise HTTPException(
                    404,
                    f"No vocal stem found for '{track_name}'. "
                    f"Run stem separation first via the generation pipeline."
                )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                404,
                f"Vocal stem not available for '{track_name}': {e}"
            )

    if not vocal_path.exists():
        raise HTTPException(404, f"No vocal stem found for '{track_name}'")

    # Load and analyze
    try:
        import soundfile as sf
        audio, sr = sf.read(str(vocal_path), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)  # to mono
    except Exception as e:
        raise HTTPException(500, f"Failed to load vocal stem: {e}")

    result = _get_vocal_analysis(audio, sr)
    result["track_name"] = track_name
    result["source"] = str(vocal_path)

    # Re-resample if fps differs from default
    if fps != 30.0:
        from src.analyzer.stems import _resample_to_fps
        rms = np.array(result["energy"])
        total_frames = int(result["duration"] * fps)
        times = np.linspace(0, result["duration"], len(rms))
        result["energy"] = _resample_to_fps(rms, times, fps, total_frames)
        result["fps"] = fps
        result["total_frames"] = total_frames

    return result


@router.get("/{track_name}/regions")
async def get_vocal_regions(
    track_name: str,
    min_duration: float = Query(0.5, ge=0.0, description="Minimum region duration in seconds"),
    merge_gap: float = Query(0.3, ge=0.0, description="Merge regions closer than this many seconds"),
):
    """Return discrete vocal regions suitable for lyric overlay timing.

    Filters and merges active regions for cleaner lyric display triggers.
    """
    # Reuse the timing endpoint logic
    timing = await get_vocal_timing(track_name)
    regions = timing["active_regions"]

    # Filter by minimum duration
    regions = [r for r in regions if r["duration"] >= min_duration]

    # Merge nearby regions
    if merge_gap > 0 and len(regions) > 1:
        merged = [regions[0]]
        for r in regions[1:]:
            prev = merged[-1]
            if r["start"] - prev["end"] <= merge_gap:
                # Merge
                merged[-1] = {
                    "start": prev["start"],
                    "end": r["end"],
                    "duration": round(r["end"] - prev["start"], 3),
                }
            else:
                merged.append(r)
        regions = merged

    return {
        "track_name": track_name,
        "regions": regions,
        "total_vocal_time": round(sum(r["duration"] for r in regions), 3),
        "total_duration": timing["duration"],
        "vocal_percentage": round(
            sum(r["duration"] for r in regions) / max(timing["duration"], 0.001) * 100, 1
        ),
    }
