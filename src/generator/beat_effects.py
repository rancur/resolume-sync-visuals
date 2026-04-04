"""
Beat-synced post-processing effects for generated videos.

Adds rhythmic visual effects (brightness flash, zoom pulse) via ffmpeg
so that video clips feel tightly locked to the music's BPM.
"""
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Section-specific effect intensities
SECTION_INTENSITIES = {
    "drop": {"flash": 0.12, "zoom": 1.015},
    "buildup": {"flash": 0.06, "zoom": 1.008},
    "build": {"flash": 0.06, "zoom": 1.008},
    "breakdown": {"flash": 0.02, "zoom": 1.003},
    "intro": {"flash": 0.02, "zoom": 1.002},
    "outro": {"flash": 0.01, "zoom": 1.001},
}


def _probe_video(video_path: Path) -> dict:
    """Probe a video file to get width, height, and fps."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return {"width": 1920, "height": 1080, "fps": 30}

    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            fps = 30
            r_frame_rate = stream.get("r_frame_rate", "30/1")
            if "/" in r_frame_rate:
                num, den = r_frame_rate.split("/")
                if int(den) > 0:
                    fps = round(int(num) / int(den))
            return {
                "width": int(stream.get("width", 1920)),
                "height": int(stream.get("height", 1080)),
                "fps": fps,
            }
    return {"width": 1920, "height": 1080, "fps": 30}


def add_beat_sync_effects(
    video_path: Path,
    output_path: Path,
    bpm: float,
    section_label: str = "drop",
    energy: float = 0.5,
) -> Path:
    """Add beat-synced visual effects to a video via ffmpeg.

    Effects:
    1. Brightness flash on every beat (sharp attack, exponential decay)
    2. Slight zoom pulse on every bar (4 beats) using zoompan
    3. Intensity scaled by section type and energy

    Args:
        video_path: Input video file path.
        output_path: Where to write the processed video.
        bpm: Beats per minute of the track.
        section_label: One of intro/buildup/drop/breakdown/outro.
        energy: 0.0-1.0 energy level for intensity scaling.

    Returns:
        The output_path on success.

    Raises:
        FileNotFoundError: If the input video does not exist.
        ValueError: If bpm is non-positive.
        RuntimeError: If ffmpeg fails.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)

    if not video_path.exists():
        raise FileNotFoundError(f"Input video not found: {video_path}")
    if bpm <= 0:
        raise ValueError(f"BPM must be positive, got {bpm}")

    beat_interval = 60.0 / bpm
    bar_interval = beat_interval * 4

    params = SECTION_INTENSITIES.get(section_label, SECTION_INTENSITIES["drop"])

    # Scale flash intensity by energy (0.5x at energy=0, 1.5x at energy=1)
    flash = params["flash"] * (0.5 + energy)
    zoom = params["zoom"]

    # Decay constant: higher = sharper flash. 30 gives ~90% decay by half-beat.
    decay = 30

    # Probe video for dimensions and fps
    info = _probe_video(video_path)
    width, height, fps = info["width"], info["height"], info["fps"]

    # Build ffmpeg filter chain
    filters = []

    # 1. Beat-synced brightness flash using eq filter
    #    brightness expression: flash * exp(-decay * mod(t, beat_interval))
    #    This spikes at each beat boundary and decays exponentially
    filters.append(
        f"eq=brightness='{flash:.6f}*exp(-{decay}*mod(t\\,{beat_interval:.6f}))'"
    )

    # 2. Zoom pulse on every bar (4 beats) using zoompan
    #    zoompan uses frame number (on), so convert bar_interval to frames
    zoom_amount = zoom - 1.0  # e.g. 0.015
    if zoom_amount > 0.001:
        bar_frames = bar_interval * fps
        z_expr = f"1+{zoom_amount:.6f}*exp(-{decay}*mod(on/{fps}\\,{bar_interval:.6f}))"
        filters.append(
            f"zoompan=z='{z_expr}':d=1:s={width}x{height}:fps={fps}"
        )

    filter_str = ",".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", filter_str,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "copy",
        str(output_path),
    ]

    logger.info(
        "Applying beat-sync effects: bpm=%.1f section=%s energy=%.2f flash=%.4f zoom=%.4f",
        bpm, section_label, energy, flash, zoom,
    )
    logger.debug("ffmpeg cmd: %s", " ".join(cmd))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.error("ffmpeg failed: %s", result.stderr[-500:] if result.stderr else "no stderr")
        raise RuntimeError(
            f"ffmpeg beat-sync failed (rc={result.returncode}): "
            f"{result.stderr[-300:] if result.stderr else ''}"
        )

    logger.info(
        "Beat-sync effects applied: %s (%.1f KB)",
        output_path, output_path.stat().st_size / 1024,
    )
    return output_path


def get_beat_interval(bpm: float) -> float:
    """Return the duration of one beat in seconds."""
    if bpm <= 0:
        raise ValueError(f"BPM must be positive, got {bpm}")
    return 60.0 / bpm


def get_bar_interval(bpm: float) -> float:
    """Return the duration of one bar (4 beats) in seconds."""
    return get_beat_interval(bpm) * 4
