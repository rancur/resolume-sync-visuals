"""
Video assembly and encoding pipeline for Resolume.

Handles:
1. Stitching multiple video segments into one continuous video
2. Crossfade transitions between segments
3. Trimming/padding to exact audio duration
4. Encoding to DXV codec (Resolume native) and HAP codec
5. 60fps output at 1080p
"""
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_ffmpeg(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    """Run an ffmpeg command, raising on failure."""
    cmd = ["ffmpeg", "-y"] + args
    logger.debug("ffmpeg command: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (rc={result.returncode}):\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return result


def _run_ffprobe(args: list[str], timeout: int = 30) -> dict:
    """Run ffprobe and return parsed JSON output."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
    ] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed (rc={result.returncode}):\n"
            f"  stderr: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Video info
# ---------------------------------------------------------------------------


def get_video_info(video_path: Path) -> dict:
    """Get video metadata: duration, resolution, fps, codec, size.

    Returns dict with keys:
        duration (float), width (int), height (int), fps (float),
        codec (str), size_bytes (int)
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    probe = _run_ffprobe(["-show_format", "-show_streams", str(video_path)])

    video_streams = [
        s for s in probe.get("streams", [])
        if s.get("codec_type") == "video"
    ]
    if not video_streams:
        raise ValueError(f"No video stream found in {video_path}")

    vs = video_streams[0]

    # Parse fps from r_frame_rate (e.g. "30/1" or "60000/1001")
    fps_str = vs.get("r_frame_rate", "0/1")
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0.0
    else:
        fps = float(fps_str)

    # Duration: prefer stream, fall back to format
    duration_str = vs.get("duration") or probe.get("format", {}).get("duration")
    duration = float(duration_str) if duration_str else 0.0

    return {
        "duration": duration,
        "width": int(vs.get("width", 0)),
        "height": int(vs.get("height", 0)),
        "fps": round(fps, 3),
        "codec": vs.get("codec_name", ""),
        "size_bytes": video_path.stat().st_size,
    }


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------


def extract_frame(video_path: Path, time_seconds: float, output_path: Path) -> Path:
    """Extract a single frame from a video at a specific time.

    Returns the output_path on success.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _run_ffmpeg([
        "-ss", str(time_seconds),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ])

    if not output_path.exists():
        raise RuntimeError(f"Frame extraction failed — output not created: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Pad or trim
# ---------------------------------------------------------------------------


def pad_or_trim(
    video_path: Path,
    output_path: Path,
    target_duration: float,
) -> Path:
    """Ensure video is exactly target_duration seconds.

    If longer: trim to target_duration.
    If shorter: loop the video to fill, then trim to exact duration.
    Returns output_path.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    info = get_video_info(video_path)
    current_duration = info["duration"]

    if current_duration <= 0:
        raise ValueError(f"Source video has invalid duration: {current_duration}")

    tolerance = 0.05  # 50ms tolerance

    if abs(current_duration - target_duration) <= tolerance:
        # Already close enough — just copy
        if video_path != output_path:
            import shutil
            shutil.copy2(str(video_path), str(output_path))
        return output_path

    if current_duration > target_duration:
        # Trim
        _run_ffmpeg([
            "-i", str(video_path),
            "-t", str(target_duration),
            "-c", "copy",
            str(output_path),
        ])
    else:
        # Loop to fill — use stream_loop
        loops_needed = int(target_duration / current_duration) + 1
        _run_ffmpeg([
            "-stream_loop", str(loops_needed),
            "-i", str(video_path),
            "-t", str(target_duration),
            "-c", "copy",
            str(output_path),
        ])

    return output_path


# ---------------------------------------------------------------------------
# FPS upscaling
# ---------------------------------------------------------------------------


def upscale_fps(
    input_path: Path,
    output_path: Path,
    target_fps: int = 60,
) -> Path:
    """Upscale video frame rate using ffmpeg minterpolate filter.

    Useful when AI models output 24fps but we need 60fps for Resolume.
    Uses motion-compensated interpolation for smooth results.
    Returns output_path.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _run_ffmpeg([
        "-i", str(input_path),
        "-vf", f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=aobmc:vsbmc=1",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        str(output_path),
    ])

    return output_path


# ---------------------------------------------------------------------------
# Stitching segments
# ---------------------------------------------------------------------------


def stitch_videos(
    segments: list[Path],
    output_path: Path,
    target_duration: float,
    crossfade_seconds: float = 0.5,
    fps: int = 60,
) -> Path:
    """Stitch multiple video segments into one continuous video.

    Uses ffmpeg xfade filter for crossfade transitions between segments.
    Trims to exact target_duration (matching audio length).
    If total segment duration < target, loops the last segment to fill.

    Args:
        segments: List of video file paths to stitch together.
        output_path: Where to write the final stitched video.
        target_duration: Exact duration in seconds (matching audio).
        crossfade_seconds: Duration of crossfade between segments.
        fps: Output frame rate.

    Returns:
        output_path on success.
    """
    if not segments:
        raise ValueError("No segments provided for stitching")

    segments = [Path(s) for s in segments]
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Single segment — just pad/trim to target
    if len(segments) == 1:
        return pad_or_trim(segments[0], output_path, target_duration)

    # Get durations of all segments
    durations = []
    for seg in segments:
        info = get_video_info(seg)
        durations.append(info["duration"])

    # Calculate total duration accounting for crossfade overlap
    total_duration = sum(durations) - crossfade_seconds * (len(segments) - 1)

    # If we need more content, loop the last segment
    if total_duration < target_duration:
        gap = target_duration - total_duration + crossfade_seconds  # +crossfade for the join
        last_info = get_video_info(segments[-1])
        loops_needed = int(gap / last_info["duration"]) + 1

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        _run_ffmpeg([
            "-stream_loop", str(loops_needed),
            "-i", str(segments[-1]),
            "-t", str(last_info["duration"] + gap),
            "-c", "copy",
            str(tmp_path),
        ])
        segments = segments[:-1] + [tmp_path]
        durations = durations[:-1] + [get_video_info(tmp_path)["duration"]]

    # Build xfade filter chain for crossfade transitions
    # For N segments, we need N-1 xfade applications
    if len(segments) == 2:
        # Simple two-segment crossfade
        offset = durations[0] - crossfade_seconds
        if offset < 0:
            offset = 0
        _run_ffmpeg([
            "-i", str(segments[0]),
            "-i", str(segments[1]),
            "-filter_complex",
            f"[0:v][1:v]xfade=transition=fade:duration={crossfade_seconds}:offset={offset},fps={fps}[outv]",
            "-map", "[outv]",
            "-t", str(target_duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            str(output_path),
        ])
    else:
        # Chain xfade filters for 3+ segments
        inputs = []
        for seg in segments:
            inputs.extend(["-i", str(seg)])

        # Build the filter graph
        filter_parts = []
        running_offset = 0.0

        # First xfade
        running_offset = durations[0] - crossfade_seconds
        if running_offset < 0:
            running_offset = 0
        filter_parts.append(
            f"[0:v][1:v]xfade=transition=fade:duration={crossfade_seconds}"
            f":offset={running_offset}[xf0]"
        )

        for i in range(2, len(segments)):
            prev_label = f"xf{i - 2}"
            out_label = f"xf{i - 1}"
            # Offset accumulates: previous offset + duration of segment being added - crossfade
            running_offset += durations[i - 1] - crossfade_seconds
            if running_offset < 0:
                running_offset = 0
            filter_parts.append(
                f"[{prev_label}][{i}:v]xfade=transition=fade"
                f":duration={crossfade_seconds}:offset={running_offset}[{out_label}]"
            )

        final_label = f"xf{len(segments) - 2}"
        filter_parts.append(f"[{final_label}]fps={fps}[outv]")
        filter_complex = ";".join(filter_parts)

        _run_ffmpeg(
            inputs + [
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                "-t", str(target_duration),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                str(output_path),
            ]
        )

    return output_path


# ---------------------------------------------------------------------------
# Resolume encoding
# ---------------------------------------------------------------------------


def encode_for_resolume(
    input_path: Path,
    output_path: Path,
    codec: str = "dxv",
    fps: int = 60,
    width: int = 1920,
    height: int = 1080,
) -> Path:
    """Encode video for Resolume playback.

    DXV: Resolume native, best performance, GPU-decoded.
    HAP: Open standard, GPU-decoded, cross-platform.

    Note: DXV files are LARGE (~30MB/sec at 1080p) — expected for GPU-decoded codecs.

    Args:
        input_path: Source video file.
        output_path: Destination .mov file.
        codec: "dxv" or "hap".
        fps: Output frame rate (default 60).
        width: Output width (default 1920).
        height: Output height (default 1080).

    Returns:
        output_path on success.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if codec not in ("dxv", "hap"):
        raise ValueError(f"Unsupported codec: {codec}. Use 'dxv' or 'hap'.")

    scale_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"

    if codec == "dxv":
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", f"{scale_filter},fps={fps}",
            "-c:v", "dxv",
            "-format", "dxt1",
            "-an",
            str(output_path),
        ])
    else:
        # HAP
        _run_ffmpeg([
            "-i", str(input_path),
            "-vf", f"{scale_filter},fps={fps}",
            "-c:v", "hap",
            "-an",
            str(output_path),
        ])

    return output_path


# ---------------------------------------------------------------------------
# Naming utility
# ---------------------------------------------------------------------------


def name_for_resolume(
    track_title: str,
    artist: str = "",
    extension: str = ".mov",
) -> str:
    """Generate output filename matching Resolume's ID3 title-based lookup.

    Resolume matches clips by track title, so the filename should be
    the sanitized title. Unsafe filesystem characters are replaced.

    Args:
        track_title: The track title (from ID3 tags or user input).
        artist: Optional artist name to include.
        extension: File extension (default .mov).

    Returns:
        A safe filename string, e.g. "Track Title - Artist.mov"
    """
    if not track_title:
        raise ValueError("track_title cannot be empty")

    # Sanitize: remove characters unsafe for filesystems
    def _sanitize(s: str) -> str:
        # Replace path separators and other problematic chars
        s = re.sub(r'[<>:"/\\|?*]', "", s)
        # Collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    name = _sanitize(track_title)
    if artist:
        name = f"{name} - {_sanitize(artist)}"

    if not extension.startswith("."):
        extension = f".{extension}"

    return f"{name}{extension}"
