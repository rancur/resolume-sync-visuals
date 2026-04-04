"""
Montage builder — creates a preview video combining all phrase clips
with the original audio track. Shows how visuals flow with the music.

Output: A single video file with all clips sequenced in order,
synced to the original audio.
"""
import json
import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def create_montage(
    clips: list[dict],
    audio_path: str | Path,
    output_path: str | Path,
    analysis: dict,
    fade_duration: float = 0.5,
) -> Path:
    """
    Create a preview montage video with all clips + original audio.

    Args:
        clips: List of clip dicts from generator (with 'path', 'start', 'end', 'label')
        audio_path: Path to the original audio file
        output_path: Where to save the montage video
        analysis: Track analysis dict
        fade_duration: Crossfade duration between clips in seconds

    Returns:
        Path to the created montage video
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path = Path(audio_path)

    if not clips:
        logger.warning("No clips to create montage from")
        return output_path

    # Filter to clips that exist
    valid_clips = [c for c in clips if Path(c.get("path", c.get("file", ""))).exists()]
    if not valid_clips:
        logger.warning("No valid clip files found")
        return output_path

    logger.info(f"Creating montage: {len(valid_clips)} clips + audio")

    # Strategy: For each phrase, loop the corresponding clip to fill
    # the phrase duration, then concatenate all with audio.
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create extended clips for each phrase
        extended_clips = []
        for i, clip in enumerate(valid_clips):
            clip_path = Path(clip.get("path", clip.get("file", "")))
            if not clip_path.exists():
                continue
            phrase_duration = clip.get("duration", 0)
            if not phrase_duration:
                start = clip.get("start", clip.get("start_time", 0))
                end = clip.get("end", clip.get("end_time", 0))
                phrase_duration = end - start
            start_time = clip.get("start", clip.get("start_time", 0))

            # Get clip's actual duration
            clip_duration = _get_duration(clip_path)
            if clip_duration is None or clip_duration < 0.1:
                continue

            # Extend clip to fill phrase duration
            extended_path = tmpdir / f"extended_{i:03d}.mp4"
            if clip_duration >= phrase_duration * 0.95:
                # Clip is long enough — just trim
                _trim_video(clip_path, extended_path, phrase_duration)
            else:
                # Loop to fill
                _loop_video(clip_path, extended_path, phrase_duration)

            extended_clips.append({
                "path": str(extended_path),
                "start": start_time,
                "duration": phrase_duration,
                "label": clip.get("label", ""),
            })

        if not extended_clips:
            logger.warning("No extended clips created")
            return output_path

        # Create concat file list
        concat_file = tmpdir / "concat.txt"
        with open(concat_file, "w") as f:
            for clip in extended_clips:
                f.write(f"file '{clip['path']}'\n")

        # Concatenate all video clips
        video_concat = tmpdir / "video_concat.mp4"
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(video_concat),
        ]

        result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"Concat failed: {result.stderr[:500]}")
            return output_path

        # Get total video duration
        video_duration = _get_duration(video_concat)

        # Mux video + audio (trim audio to match video length)
        mux_cmd = [
            "ffmpeg", "-y",
            "-i", str(video_concat),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-t", str(video_duration),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-movflags", "+faststart",
            str(output_path),
        ]

        result = subprocess.run(mux_cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f"Mux failed: {result.stderr[:500]}")
            # Fall back to video-only
            import shutil
            shutil.copy2(video_concat, output_path)

    logger.info(f"Montage created: {output_path} ({_get_duration(output_path):.1f}s)")
    return output_path


def _get_duration(path: Path) -> float | None:
    """Get video duration in seconds."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return None


def _trim_video(src: Path, dst: Path, duration: float):
    """Trim video to exact duration."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        str(dst),
    ]
    subprocess.run(cmd, capture_output=True, timeout=120)


def _loop_video(src: Path, dst: Path, target_duration: float):
    """Loop video to fill target duration."""
    src_duration = _get_duration(src)
    if not src_duration or src_duration < 0.1:
        return

    n_loops = int(target_duration / src_duration) + 1
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", str(n_loops),
        "-i", str(src),
        "-t", str(target_duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an",
        str(dst),
    ]
    subprocess.run(cmd, capture_output=True, timeout=120)
