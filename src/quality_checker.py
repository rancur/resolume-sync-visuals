"""
Automatic quality checks on generated videos.

Post-generation quality pipeline that catches common AI video defects:
1. Black frame detection (near-black frames = failed generation)
2. Frozen video detection (no motion = static image)
3. Color banding detection (quantization artifacts)
4. Temporal coherence (sudden visual jumps between segments)
5. Duration accuracy (video matches expected audio length)
6. Technical validation (resolution, codec, file size)

Each check produces a 0-100 sub-score. The final quality score is a
weighted average. Videos below the configurable threshold are flagged
for regeneration.
"""
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_MIN_SCORE = 60
DEFAULT_MAX_RETRIES = 2
DEFAULT_SAMPLE_POINTS = 10

# Check weights (sum to 1.0)
CHECK_WEIGHTS = {
    "black_frames": 0.20,
    "frozen_video": 0.25,
    "color_banding": 0.10,
    "temporal_coherence": 0.15,
    "duration_accuracy": 0.15,
    "technical": 0.15,
}


@dataclass
class CheckResult:
    """Result of a single quality check."""
    name: str
    score: int  # 0-100
    passed: bool
    details: str = ""
    severity: str = "info"  # info, warning, error


@dataclass
class QualityReport:
    """Full quality report for a generated video."""
    video_path: str
    overall_score: int = 0
    passed: bool = False
    checks: list[CheckResult] = field(default_factory=list)
    sample_frames: list[str] = field(default_factory=list)  # paths to sampled frames
    retry_count: int = 0
    max_retries: int = DEFAULT_MAX_RETRIES
    should_regenerate: bool = False

    def to_dict(self) -> dict:
        return {
            "video_path": self.video_path,
            "overall_score": self.overall_score,
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "score": c.score,
                    "passed": c.passed,
                    "details": c.details,
                    "severity": c.severity,
                }
                for c in self.checks
            ],
            "sample_frames": self.sample_frames,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "should_regenerate": self.should_regenerate,
        }


def run_quality_checks(
    video_path: str | Path,
    expected_duration: Optional[float] = None,
    expected_width: int = 1920,
    expected_height: int = 1080,
    min_score: int = DEFAULT_MIN_SCORE,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_count: int = 0,
    sample_points: int = DEFAULT_SAMPLE_POINTS,
) -> QualityReport:
    """Run all quality checks on a generated video.

    Args:
        video_path: Path to the video file.
        expected_duration: Expected duration in seconds (for accuracy check).
        expected_width: Expected width in pixels.
        expected_height: Expected height in pixels.
        min_score: Minimum passing score (0-100).
        max_retries: Maximum regeneration attempts.
        retry_count: Current retry count.
        sample_points: Number of frames to sample for visual checks.

    Returns:
        QualityReport with scores and regeneration recommendation.
    """
    video_path = Path(video_path)
    report = QualityReport(
        video_path=str(video_path),
        retry_count=retry_count,
        max_retries=max_retries,
    )

    if not video_path.exists():
        report.checks.append(CheckResult(
            name="file_exists",
            score=0,
            passed=False,
            details=f"Video file not found: {video_path}",
            severity="error",
        ))
        report.should_regenerate = retry_count < max_retries
        return report

    # Get video info via ffprobe
    video_info = _probe_video(video_path)
    if not video_info:
        report.checks.append(CheckResult(
            name="probe",
            score=0,
            passed=False,
            details="Failed to probe video with ffprobe",
            severity="error",
        ))
        report.should_regenerate = retry_count < max_retries
        return report

    # Run individual checks
    report.checks.append(_check_technical(video_info, expected_width, expected_height))
    report.checks.append(_check_duration_accuracy(video_info, expected_duration))
    report.checks.append(_check_black_frames(video_path, video_info, sample_points))
    report.checks.append(_check_frozen_video(video_path, video_info, sample_points))
    report.checks.append(_check_color_banding(video_path, video_info, sample_points))
    report.checks.append(_check_temporal_coherence(video_path, video_info, sample_points))

    # Calculate weighted overall score
    total_weight = 0.0
    weighted_sum = 0.0
    for check in report.checks:
        weight = CHECK_WEIGHTS.get(check.name, 0.1)
        weighted_sum += check.score * weight
        total_weight += weight

    report.overall_score = round(weighted_sum / total_weight) if total_weight > 0 else 0
    report.passed = report.overall_score >= min_score
    report.should_regenerate = (not report.passed) and (retry_count < max_retries)

    logger.info(
        f"Quality check: {video_path.name} -> score={report.overall_score}/100 "
        f"({'PASS' if report.passed else 'FAIL'})"
    )

    return report


def _probe_video(video_path: Path) -> Optional[dict]:
    """Probe video file with ffprobe, return parsed info."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        probe = json.loads(result.stdout)

        video_streams = [
            s for s in probe.get("streams", [])
            if s.get("codec_type") == "video"
        ]
        if not video_streams:
            return None

        vs = video_streams[0]
        fmt = probe.get("format", {})

        return {
            "codec": vs.get("codec_name", ""),
            "width": int(vs.get("width", 0)),
            "height": int(vs.get("height", 0)),
            "duration": float(vs.get("duration", 0) or fmt.get("duration", 0)),
            "fps": _parse_fps(vs.get("r_frame_rate", "30/1")),
            "bitrate": int(fmt.get("bit_rate", 0)),
            "size_bytes": int(fmt.get("size", 0)),
            "nb_frames": int(vs.get("nb_frames", 0) or 0),
            "pix_fmt": vs.get("pix_fmt", ""),
        }
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
        return None


def _parse_fps(fps_str: str) -> float:
    """Parse ffprobe frame rate string (e.g., '30/1', '29.97')."""
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            return float(num) / float(den)
        return float(fps_str)
    except (ValueError, ZeroDivisionError):
        return 30.0


def _check_technical(info: dict, expected_w: int, expected_h: int) -> CheckResult:
    """Check technical specs: resolution, codec, file size."""
    score = 100
    issues = []

    # Resolution
    if info["width"] != expected_w or info["height"] != expected_h:
        score -= 30
        issues.append(
            f"Resolution {info['width']}x{info['height']} "
            f"(expected {expected_w}x{expected_h})"
        )

    # File size sanity (>10KB for a real video)
    if info["size_bytes"] < 10240:
        score -= 40
        issues.append(f"File suspiciously small ({info['size_bytes']} bytes)")

    # Codec present
    if not info["codec"]:
        score -= 20
        issues.append("No codec detected")

    details = "; ".join(issues) if issues else "All technical checks passed"
    return CheckResult(
        name="technical",
        score=max(0, score),
        passed=score >= 70,
        details=details,
        severity="error" if score < 50 else "info",
    )


def _check_duration_accuracy(
    info: dict,
    expected_duration: Optional[float],
) -> CheckResult:
    """Check if video duration matches expected audio duration."""
    if expected_duration is None or expected_duration <= 0:
        return CheckResult(
            name="duration_accuracy",
            score=90,  # Can't check, assume reasonable
            passed=True,
            details="No expected duration provided, skipping accuracy check",
        )

    actual = info["duration"]
    if actual <= 0:
        return CheckResult(
            name="duration_accuracy",
            score=0,
            passed=False,
            details="Video has zero duration",
            severity="error",
        )

    diff = abs(actual - expected_duration)
    pct_diff = diff / expected_duration * 100

    if pct_diff <= 2:
        score = 100
    elif pct_diff <= 5:
        score = 85
    elif pct_diff <= 10:
        score = 70
    elif pct_diff <= 20:
        score = 50
    else:
        score = max(0, 30 - int(pct_diff))

    return CheckResult(
        name="duration_accuracy",
        score=score,
        passed=score >= 60,
        details=f"Duration: {actual:.1f}s (expected {expected_duration:.1f}s, diff={diff:.1f}s, {pct_diff:.1f}%)",
        severity="warning" if score < 70 else "info",
    )


def _check_black_frames(
    video_path: Path,
    info: dict,
    sample_points: int,
) -> CheckResult:
    """Detect near-black frames by sampling at intervals.

    Uses ffmpeg to extract frames and checks their average brightness.
    """
    duration = info["duration"]
    if duration <= 0:
        return CheckResult(
            name="black_frames",
            score=0,
            passed=False,
            details="Cannot check: video has no duration",
            severity="error",
        )

    # Sample frame brightness at intervals
    black_count = 0
    total_sampled = 0
    brightness_values = []

    for i in range(sample_points):
        t = (i + 0.5) * duration / sample_points
        brightness = _get_frame_brightness(video_path, t)
        if brightness is not None:
            brightness_values.append(brightness)
            total_sampled += 1
            if brightness < 10:  # Near-black threshold (0-255 scale)
                black_count += 1

    if total_sampled == 0:
        return CheckResult(
            name="black_frames",
            score=50,
            passed=True,
            details="Could not sample frames (ffmpeg may not be available)",
            severity="warning",
        )

    black_ratio = black_count / total_sampled
    avg_brightness = sum(brightness_values) / len(brightness_values)

    if black_ratio > 0.5:
        score = 10
    elif black_ratio > 0.2:
        score = 40
    elif black_ratio > 0.1:
        score = 70
    elif avg_brightness < 20:
        score = 60  # Very dark but not fully black
    else:
        score = 100

    return CheckResult(
        name="black_frames",
        score=score,
        passed=score >= 50,
        details=f"{black_count}/{total_sampled} black frames, avg brightness={avg_brightness:.0f}",
        severity="error" if score < 30 else ("warning" if score < 70 else "info"),
    )


def _check_frozen_video(
    video_path: Path,
    info: dict,
    sample_points: int,
) -> CheckResult:
    """Detect frozen/static video by comparing consecutive frame differences.

    A frozen video will have very low differences between sampled frames.
    """
    duration = info["duration"]
    if duration < 1.0:
        return CheckResult(
            name="frozen_video",
            score=80,
            passed=True,
            details="Video too short for freeze detection",
        )

    diffs = []
    for i in range(min(sample_points - 1, 8)):
        t1 = (i + 0.5) * duration / sample_points
        t2 = (i + 1.5) * duration / sample_points
        diff = _get_frame_difference(video_path, t1, t2)
        if diff is not None:
            diffs.append(diff)

    if not diffs:
        return CheckResult(
            name="frozen_video",
            score=50,
            passed=True,
            details="Could not compute frame differences",
            severity="warning",
        )

    avg_diff = sum(diffs) / len(diffs)
    max_diff = max(diffs)
    frozen_count = sum(1 for d in diffs if d < 0.5)
    frozen_ratio = frozen_count / len(diffs)

    if frozen_ratio > 0.8:
        score = 10  # Almost entirely frozen
    elif frozen_ratio > 0.5:
        score = 40
    elif avg_diff < 1.0:
        score = 50  # Very low motion overall
    elif avg_diff < 3.0:
        score = 75  # Low but present motion
    else:
        score = 100

    return CheckResult(
        name="frozen_video",
        score=score,
        passed=score >= 40,
        details=f"Avg frame diff={avg_diff:.1f}, frozen={frozen_count}/{len(diffs)}, max_diff={max_diff:.1f}",
        severity="error" if score < 30 else ("warning" if score < 60 else "info"),
    )


def _check_color_banding(
    video_path: Path,
    info: dict,
    sample_points: int,
) -> CheckResult:
    """Detect color banding (quantization artifacts in gradients).

    Checks pixel format and bitrate as proxies for banding risk.
    Higher bitrate and 10-bit formats have less banding.
    """
    pix_fmt = info.get("pix_fmt", "")
    bitrate = info.get("bitrate", 0)
    duration = info.get("duration", 0)

    score = 100
    issues = []

    # Pixel format check
    if "10" in pix_fmt or "12" in pix_fmt:
        pass  # 10/12-bit, low banding risk
    elif "8" in pix_fmt or pix_fmt in ("yuv420p", "yuv422p", "yuv444p"):
        score -= 10  # 8-bit is acceptable but more prone to banding
        issues.append(f"8-bit pixel format ({pix_fmt})")

    # Bitrate check (bits per second)
    if duration > 0 and bitrate > 0:
        # Calculate bits per pixel per frame
        pixels = info["width"] * info["height"]
        fps = info["fps"]
        if pixels > 0 and fps > 0:
            bpp = bitrate / (pixels * fps)
            if bpp < 0.05:
                score -= 30
                issues.append(f"Very low bitrate ({bitrate // 1000}kbps, {bpp:.3f} bpp)")
            elif bpp < 0.1:
                score -= 15
                issues.append(f"Low bitrate ({bitrate // 1000}kbps)")

    details = "; ".join(issues) if issues else "No banding indicators detected"
    return CheckResult(
        name="color_banding",
        score=max(0, score),
        passed=score >= 50,
        details=details,
        severity="warning" if score < 70 else "info",
    )


def _check_temporal_coherence(
    video_path: Path,
    info: dict,
    sample_points: int,
) -> CheckResult:
    """Check for sudden visual jumps (poor segment transitions).

    Samples pairs of frames close together. Occasional large jumps
    at segment boundaries are expected, but many indicate poor stitching.
    """
    duration = info["duration"]
    if duration < 2.0:
        return CheckResult(
            name="temporal_coherence",
            score=85,
            passed=True,
            details="Video too short for coherence check",
        )

    diffs = []
    # Check closely-spaced frame pairs (0.5s apart)
    for i in range(min(sample_points, 8)):
        t = (i + 0.5) * duration / sample_points
        t2 = min(t + 0.5, duration - 0.1)
        if t2 <= t:
            continue
        diff = _get_frame_difference(video_path, t, t2)
        if diff is not None:
            diffs.append(diff)

    if not diffs:
        return CheckResult(
            name="temporal_coherence",
            score=60,
            passed=True,
            details="Could not compute temporal coherence",
            severity="warning",
        )

    avg_diff = sum(diffs) / len(diffs)
    # Count "jumps" - frame differences much larger than average
    jump_threshold = max(avg_diff * 3, 15.0)
    jumps = sum(1 for d in diffs if d > jump_threshold)
    jump_ratio = jumps / len(diffs)

    if jump_ratio > 0.4:
        score = 30
    elif jump_ratio > 0.2:
        score = 60
    elif jumps > 0:
        score = 80
    else:
        score = 100

    return CheckResult(
        name="temporal_coherence",
        score=score,
        passed=score >= 50,
        details=f"Avg diff={avg_diff:.1f}, jumps={jumps}/{len(diffs)} (threshold={jump_threshold:.1f})",
        severity="warning" if score < 60 else "info",
    )


# ---------------------------------------------------------------------------
# Frame analysis helpers (using ffmpeg)
# ---------------------------------------------------------------------------

def _get_frame_brightness(video_path: Path, time_sec: float) -> Optional[float]:
    """Extract a frame and compute average brightness (0-255)."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-ss", f"{time_sec:.2f}",
                "-i", str(video_path),
                "-vframes", "1",
                "-f", "rawvideo", "-pix_fmt", "gray",
                "-v", "quiet",
                "pipe:1",
            ],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        pixels = result.stdout
        if not pixels:
            return None
        return sum(pixels) / len(pixels)
    except Exception:
        return None


def _get_frame_difference(
    video_path: Path,
    time1: float,
    time2: float,
) -> Optional[float]:
    """Compute average pixel difference between two frames."""
    try:
        # Extract both frames as grayscale raw
        frame1 = _extract_raw_frame(video_path, time1)
        frame2 = _extract_raw_frame(video_path, time2)

        if frame1 is None or frame2 is None:
            return None

        # Ensure same length
        min_len = min(len(frame1), len(frame2))
        if min_len == 0:
            return None

        # Average absolute difference
        total_diff = sum(
            abs(frame1[i] - frame2[i])
            for i in range(min_len)
        )
        return total_diff / min_len
    except Exception:
        return None


def _extract_raw_frame(video_path: Path, time_sec: float) -> Optional[bytes]:
    """Extract a single frame as grayscale raw bytes."""
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-ss", f"{time_sec:.2f}",
                "-i", str(video_path),
                "-vframes", "1",
                "-f", "rawvideo", "-pix_fmt", "gray",
                "-s", "160x90",  # Downscale for fast comparison
                "-v", "quiet",
                "pipe:1",
            ],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        return result.stdout
    except Exception:
        return None
