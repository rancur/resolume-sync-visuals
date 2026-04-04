"""
Visual consistency scoring across a full set.

Scores how visually consistent an entire set's worth of generated
videos are. Uses color histogram and brightness analysis to detect
outlier tracks that look different from the rest.

Lightweight alternative to CLIP embeddings -- works without GPU or
large model downloads. For production, add CLIP scoring as an
optional upgrade.
"""
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Thresholds
DEFAULT_OUTLIER_THRESHOLD = 0.6  # Similarity below this = outlier
DEFAULT_SAMPLE_FRAMES = 5        # Frames to sample per video


@dataclass
class TrackVisualProfile:
    """Visual characteristics extracted from a track's video."""
    track_title: str
    avg_brightness: float = 0.0
    color_histogram: list[float] = field(default_factory=list)  # 16-bin HSV histogram
    avg_saturation: float = 0.0
    dominant_hue: float = 0.0
    file_path: str = ""

    def to_dict(self) -> dict:
        return {
            "track_title": self.track_title,
            "avg_brightness": round(self.avg_brightness, 2),
            "avg_saturation": round(self.avg_saturation, 2),
            "dominant_hue": round(self.dominant_hue, 2),
            "file_path": self.file_path,
        }


@dataclass
class ConsistencyReport:
    """Consistency report for a set of tracks."""
    brand: str = ""
    total_tracks: int = 0
    avg_similarity: float = 0.0
    outliers: list[dict] = field(default_factory=list)
    similarity_matrix: list[list[float]] = field(default_factory=list)
    track_titles: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    score: int = 0  # 0-100 overall consistency score

    def to_dict(self) -> dict:
        return {
            "brand": self.brand,
            "total_tracks": self.total_tracks,
            "avg_similarity": round(self.avg_similarity, 3),
            "score": self.score,
            "outliers": self.outliers,
            "suggestions": self.suggestions,
            "track_titles": self.track_titles,
            "similarity_matrix": [
                [round(v, 3) for v in row]
                for row in self.similarity_matrix
            ],
        }


def extract_visual_profile(
    video_path: str | Path,
    sample_frames: int = DEFAULT_SAMPLE_FRAMES,
) -> Optional[TrackVisualProfile]:
    """Extract visual characteristics from a video.

    Samples frames and computes color/brightness statistics.

    Args:
        video_path: Path to video file.
        sample_frames: Number of frames to sample.

    Returns:
        TrackVisualProfile, or None if extraction fails.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        return None

    title = video_path.stem.replace("_", " ").replace("-", " ")
    profile = TrackVisualProfile(track_title=title, file_path=str(video_path))

    # Get video duration
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(video_path)],
            capture_output=True, text=True, timeout=10,
        )
        info = json.loads(result.stdout)
        duration = float(info.get("format", {}).get("duration", 0))
    except Exception:
        duration = 0

    if duration <= 0:
        return profile

    # Sample frames and extract color stats
    brightness_values = []
    hue_values = []
    sat_values = []

    for i in range(sample_frames):
        t = (i + 0.5) * duration / sample_frames
        stats = _extract_frame_color_stats(video_path, t)
        if stats:
            brightness_values.append(stats["brightness"])
            hue_values.append(stats["hue"])
            sat_values.append(stats["saturation"])

    if brightness_values:
        profile.avg_brightness = float(np.mean(brightness_values))
        profile.avg_saturation = float(np.mean(sat_values))
        profile.dominant_hue = float(np.median(hue_values))

    return profile


def compute_similarity(a: TrackVisualProfile, b: TrackVisualProfile) -> float:
    """Compute visual similarity between two track profiles.

    Uses weighted combination of brightness, saturation, and hue similarity.

    Returns:
        Similarity score 0.0-1.0 (1.0 = identical).
    """
    # Brightness similarity (0-255 range)
    bright_diff = abs(a.avg_brightness - b.avg_brightness)
    bright_sim = max(0, 1.0 - bright_diff / 128)

    # Saturation similarity (0-255 range)
    sat_diff = abs(a.avg_saturation - b.avg_saturation)
    sat_sim = max(0, 1.0 - sat_diff / 128)

    # Hue similarity (0-180 range, circular)
    hue_diff = abs(a.dominant_hue - b.dominant_hue)
    hue_diff = min(hue_diff, 180 - hue_diff)  # Circular distance
    hue_sim = max(0, 1.0 - hue_diff / 90)

    # Weighted combination
    return 0.3 * bright_sim + 0.3 * sat_sim + 0.4 * hue_sim


def score_consistency(
    profiles: list[TrackVisualProfile],
    brand: str = "",
    outlier_threshold: float = DEFAULT_OUTLIER_THRESHOLD,
) -> ConsistencyReport:
    """Score visual consistency across a set of track profiles.

    Computes pairwise similarity matrix, identifies outliers, and
    generates suggestions.

    Args:
        profiles: List of TrackVisualProfile for each track.
        brand: Brand name for the report.
        outlier_threshold: Similarity below this = outlier.

    Returns:
        ConsistencyReport with scores, outliers, and suggestions.
    """
    n = len(profiles)
    report = ConsistencyReport(
        brand=brand,
        total_tracks=n,
        track_titles=[p.track_title for p in profiles],
    )

    if n < 2:
        report.score = 100
        report.avg_similarity = 1.0
        return report

    # Compute pairwise similarity matrix
    sim_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                sim_matrix[i, j] = 1.0
            else:
                sim_matrix[i, j] = compute_similarity(profiles[i], profiles[j])

    report.similarity_matrix = sim_matrix.tolist()

    # Average similarity per track (excluding self)
    avg_sims = []
    for i in range(n):
        others = [sim_matrix[i, j] for j in range(n) if i != j]
        avg_sims.append(float(np.mean(others)) if others else 1.0)

    report.avg_similarity = float(np.mean(avg_sims))
    report.score = min(100, max(0, int(report.avg_similarity * 100)))

    # Identify outliers
    for i, (profile, avg_sim) in enumerate(zip(profiles, avg_sims)):
        if avg_sim < outlier_threshold:
            report.outliers.append({
                "track_title": profile.track_title,
                "avg_similarity": round(avg_sim, 3),
                "brightness": round(profile.avg_brightness, 1),
                "saturation": round(profile.avg_saturation, 1),
                "dominant_hue": round(profile.dominant_hue, 1),
            })

    # Generate suggestions
    if report.outliers:
        for outlier in report.outliers:
            title = outlier["track_title"]
            report.suggestions.append(
                f"Track '{title}' is visually inconsistent "
                f"(similarity: {outlier['avg_similarity']:.0%}). "
                f"Consider regenerating with adjusted prompts to match the set."
            )

    if report.avg_similarity < 0.5:
        report.suggestions.append(
            "Overall consistency is low. Consider using a consistent "
            "style_override across all tracks or tightening the brand guide."
        )

    return report


def _extract_frame_color_stats(
    video_path: Path,
    time_sec: float,
) -> Optional[dict]:
    """Extract color statistics from a single frame.

    Returns dict with brightness, hue, saturation (0-255/0-180 scale).
    """
    try:
        # Extract frame as raw RGB
        result = subprocess.run(
            [
                "ffmpeg", "-ss", f"{time_sec:.2f}",
                "-i", str(video_path),
                "-vframes", "1",
                "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", "80x45",  # Small for fast processing
                "-v", "quiet",
                "pipe:1",
            ],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout:
            return None

        pixels = np.frombuffer(result.stdout, dtype=np.uint8)
        if len(pixels) < 3:
            return None

        pixels = pixels.reshape(-1, 3)

        # Simple color stats from RGB
        r, g, b = pixels[:, 0].astype(float), pixels[:, 1].astype(float), pixels[:, 2].astype(float)

        brightness = float(np.mean(0.299 * r + 0.587 * g + 0.114 * b))

        # Simple hue approximation
        max_c = np.maximum(r, np.maximum(g, b))
        min_c = np.minimum(r, np.minimum(g, b))
        delta = max_c - min_c + 1e-6

        # Saturation
        saturation = float(np.mean(delta / (max_c + 1e-6)) * 255)

        # Dominant hue (simplified)
        hue_r = np.where(max_c == r, ((g - b) / delta) % 6, 0)
        hue_g = np.where(max_c == g, ((b - r) / delta) + 2, 0)
        hue_b = np.where(max_c == b, ((r - g) / delta) + 4, 0)
        hue = (hue_r + hue_g + hue_b) * 30  # Scale to 0-180
        dominant_hue = float(np.median(hue))

        return {
            "brightness": brightness,
            "saturation": saturation,
            "hue": dominant_hue,
        }
    except Exception:
        return None
