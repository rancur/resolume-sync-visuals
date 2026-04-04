"""
Key change detection and visual color mapping.

Detects musical key changes within a track using chromagram analysis
and maps keys to colors using established synesthesia/Camelot mappings.

Musical key -> color mapping follows two principles:
1. Major keys = warm colors, minor keys = cool colors
2. Adjacent keys on the Camelot wheel get neighboring colors on the spectrum

Key changes trigger smooth color palette transitions over a configurable
number of beats (default: 4 beats).
"""
import logging
from typing import Optional

import librosa
import numpy as np

logger = logging.getLogger(__name__)

# Transition config defaults
DEFAULT_TRANSITION_BEATS = 4

# ── Key-to-color mapping ─────────────────────────────────────────────
# Based on Scriabin's synesthesia + Camelot wheel adjacency.
# Major keys: warm spectrum (red/orange/yellow/green)
# Minor keys: cool spectrum (blue/purple/teal)

KEY_COLOR_MAP = {
    # Major keys (warm)
    "C":  "#FF4444",   # Red
    "G":  "#FF6B35",   # Orange-red
    "D":  "#FF9500",   # Orange
    "A":  "#FFB800",   # Amber
    "E":  "#FFD700",   # Gold
    "B":  "#CCFF00",   # Yellow-green
    "F#": "#66FF00",   # Green
    "Gb": "#66FF00",   # Green (enharmonic)
    "Db": "#00CC88",   # Teal
    "Ab": "#00AAFF",   # Sky blue
    "Eb": "#6B5BFF",   # Periwinkle
    "Bb": "#CC44FF",   # Violet
    "F":  "#FF4488",   # Pink

    # Minor keys (cool)
    "Am":  "#4444FF",   # Blue
    "Em":  "#3366CC",   # Steel blue
    "Bm":  "#2288AA",   # Teal blue
    "F#m": "#22AA88",   # Sea green
    "Dbm": "#228866",   # Dark teal
    "C#m": "#228866",   # Dark teal (enharmonic)
    "Abm": "#445588",   # Slate blue
    "G#m": "#445588",   # Slate blue (enharmonic)
    "Ebm": "#664488",   # Purple
    "D#m": "#664488",   # Purple (enharmonic)
    "Bbm": "#884466",   # Mauve
    "A#m": "#884466",   # Mauve (enharmonic)
    "Fm":  "#6644AA",   # Deep purple
    "Cm":  "#5544CC",   # Indigo
    "Gm":  "#4466AA",   # Navy blue
    "Dm":  "#336699",   # Medium blue
}

# Chromatic scale for index mapping
_CHROMA_KEYS_MAJOR = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
_CHROMA_KEYS_MINOR = ["Cm", "C#m", "Dm", "D#m", "Em", "Fm", "F#m", "Gm", "G#m", "Am", "A#m", "Bm"]


def detect_key_changes(
    audio_path: str,
    sr: int = 22050,
    hop_length: int = 512,
    segment_length_sec: float = 4.0,
) -> list[dict]:
    """Detect key changes within a track.

    Divides the track into segments and estimates the key for each.
    A key change is detected when adjacent segments have different keys.

    Args:
        audio_path: Path to audio file.
        sr: Sample rate.
        hop_length: Hop length for chromagram.
        segment_length_sec: Length of each analysis segment in seconds.

    Returns:
        List of key change events:
        [{"time": float, "from_key": str, "to_key": str, "confidence": float}]
    """
    logger.info(f"Detecting key changes: {audio_path}")

    y, sr_actual = librosa.load(audio_path, sr=sr, mono=True)
    duration = librosa.get_duration(y=y, sr=sr_actual)

    # Compute chromagram
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr_actual, hop_length=hop_length)
    chroma_times = librosa.frames_to_time(
        np.arange(chroma.shape[1]), sr=sr_actual, hop_length=hop_length
    )

    # Segment the chromagram
    segment_frames = int(segment_length_sec * sr_actual / hop_length)
    n_segments = max(1, chroma.shape[1] // segment_frames)

    keys = []
    for i in range(n_segments):
        start_frame = i * segment_frames
        end_frame = min((i + 1) * segment_frames, chroma.shape[1])
        segment_chroma = chroma[:, start_frame:end_frame]

        key, is_major, confidence = _estimate_key(segment_chroma)
        time_sec = float(chroma_times[start_frame]) if start_frame < len(chroma_times) else 0.0

        keys.append({
            "time": round(time_sec, 2),
            "key": key,
            "is_major": is_major,
            "confidence": round(confidence, 3),
        })

    # Find key changes
    changes = []
    for i in range(1, len(keys)):
        if keys[i]["key"] != keys[i - 1]["key"]:
            changes.append({
                "time": keys[i]["time"],
                "from_key": keys[i - 1]["key"],
                "to_key": keys[i]["key"],
                "confidence": min(keys[i - 1]["confidence"], keys[i]["confidence"]),
            })

    logger.info(f"  Found {len(changes)} key changes in {duration:.0f}s track")
    return changes


def _estimate_key(chroma: np.ndarray) -> tuple[str, bool, float]:
    """Estimate the key from a chromagram segment.

    Uses the Krumhansl-Kessler key profiles.

    Returns:
        (key_name, is_major, confidence)
    """
    # Krumhansl-Kessler major and minor profiles
    major_profile = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor_profile = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

    # Average chroma over time
    chroma_avg = np.mean(chroma, axis=1)
    if np.sum(chroma_avg) < 1e-6:
        return "C", True, 0.0

    # Normalize
    chroma_avg = chroma_avg / np.sum(chroma_avg)

    best_key = "C"
    best_corr = -1.0
    is_major = True

    for shift in range(12):
        shifted = np.roll(chroma_avg, -shift)

        # Major correlation
        maj_corr = float(np.corrcoef(shifted, major_profile)[0, 1])
        if maj_corr > best_corr:
            best_corr = maj_corr
            best_key = _CHROMA_KEYS_MAJOR[shift]
            is_major = True

        # Minor correlation
        min_corr = float(np.corrcoef(shifted, minor_profile)[0, 1])
        if min_corr > best_corr:
            best_corr = min_corr
            best_key = _CHROMA_KEYS_MINOR[shift]
            is_major = False

    confidence = max(0.0, min(1.0, (best_corr + 1) / 2))
    return best_key, is_major, confidence


def key_to_color(key: str, brand_config: Optional[dict] = None) -> str:
    """Map a musical key to a hex color.

    Checks brand guide first for custom key_colors, falls back to defaults.

    Args:
        key: Musical key (e.g., "Am", "C", "F#m").
        brand_config: Optional brand guide with custom key_colors mapping.

    Returns:
        Hex color string.
    """
    # Check brand config for custom mapping
    if brand_config:
        custom = brand_config.get("key_colors", {})
        if key in custom:
            return custom[key]

    return KEY_COLOR_MAP.get(key, "#808080")


def key_change_to_color_transition(
    from_key: str,
    to_key: str,
    transition_beats: int = DEFAULT_TRANSITION_BEATS,
    brand_config: Optional[dict] = None,
) -> dict:
    """Generate a color transition spec for a key change.

    Args:
        from_key: Starting key.
        to_key: Target key.
        transition_beats: Number of beats for the transition.
        brand_config: Optional brand guide.

    Returns:
        Transition spec dict with from_color, to_color, beats, and
        intermediate steps.
    """
    from_color = key_to_color(from_key, brand_config)
    to_color = key_to_color(to_key, brand_config)

    # Parse hex colors to RGB
    from_rgb = _hex_to_rgb(from_color)
    to_rgb = _hex_to_rgb(to_color)

    # Generate intermediate colors
    steps = []
    for i in range(transition_beats + 1):
        t = i / max(transition_beats, 1)
        r = int(from_rgb[0] + (to_rgb[0] - from_rgb[0]) * t)
        g = int(from_rgb[1] + (to_rgb[1] - from_rgb[1]) * t)
        b = int(from_rgb[2] + (to_rgb[2] - from_rgb[2]) * t)
        steps.append(f"#{r:02x}{g:02x}{b:02x}")

    return {
        "from_key": from_key,
        "to_key": to_key,
        "from_color": from_color,
        "to_color": to_color,
        "transition_beats": transition_beats,
        "steps": steps,
    }


def apply_key_colors_to_segments(
    segments: list[dict],
    key_changes: list[dict],
    bpm: float,
    brand_config: Optional[dict] = None,
    transition_beats: int = DEFAULT_TRANSITION_BEATS,
) -> list[dict]:
    """Add key-based color metadata to segments.

    For each segment, determines the active key and adds color info.
    If a key change occurs within a segment, adds a transition spec.

    Args:
        segments: Pipeline segments with 'start', 'end' fields.
        key_changes: Key change events from detect_key_changes().
        bpm: Track BPM for transition timing.
        brand_config: Optional brand guide.
        transition_beats: Beats for color transition.

    Returns:
        Same segments with added 'key_color' metadata.
    """
    if not key_changes:
        return segments

    beat_duration = 60.0 / bpm if bpm > 0 else 0.5

    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)

        # Find which key is active at this segment's start
        active_key = key_changes[0].get("from_key", "C") if key_changes else "C"
        for kc in key_changes:
            if kc["time"] <= seg_start:
                active_key = kc["to_key"]
            else:
                break

        seg["key_color"] = {
            "key": active_key,
            "color": key_to_color(active_key, brand_config),
        }

        # Check for key changes within this segment
        for kc in key_changes:
            if seg_start < kc["time"] < seg_end:
                transition = key_change_to_color_transition(
                    kc["from_key"], kc["to_key"],
                    transition_beats, brand_config,
                )
                transition["time"] = kc["time"]
                transition["transition_duration"] = round(
                    transition_beats * beat_duration, 2
                )
                seg["key_color"]["transition"] = transition
                # Update active key to the post-change key
                seg["key_color"]["key"] = kc["to_key"]
                seg["key_color"]["color"] = key_to_color(kc["to_key"], brand_config)
                break  # Only handle first key change per segment

    return segments


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return (128, 128, 128)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )
