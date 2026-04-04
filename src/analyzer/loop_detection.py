"""
Sample and loop detection for visual repetition patterns.

Detects repeating audio patterns using self-similarity analysis and
maps them to visual repetition strategies. When a 4-bar loop repeats,
the visual echoes that repetition with configurable style.

Repetition strategies:
- evolving: each repeat slightly transforms the visual
- rotating: color palette rotates on each repetition
- exact: identical visual loop (hypnotic effect)
- transforming: progressive mutation across repeats
"""
import logging
from typing import Optional

import librosa
import numpy as np

logger = logging.getLogger(__name__)

# Default config
DEFAULT_REPETITION_STYLE = "evolving"
MIN_LOOP_DURATION_BEATS = 4
MAX_LOOP_DURATION_BEATS = 32


def detect_loops(
    audio_path: str,
    bpm: float = 128.0,
    sr: int = 22050,
    hop_length: int = 512,
) -> list[dict]:
    """Detect repeating loop patterns in audio.

    Uses chromagram self-similarity matrix to find repeating sections.

    Args:
        audio_path: Path to audio file.
        bpm: Beats per minute (for beat-aligned loop boundaries).
        sr: Sample rate.
        hop_length: Hop length for feature extraction.

    Returns:
        List of detected loops:
        [{
            "start": float,      # Start time in seconds
            "end": float,        # End time of one repeat
            "duration": float,   # Duration of one loop cycle
            "duration_beats": int,
            "repetitions": int,  # How many times it repeats
            "confidence": float, # 0-1 detection confidence
            "total_duration": float,  # Total duration including all repeats
        }]
    """
    logger.info(f"Detecting loops in: {audio_path}")

    y, sr_actual = librosa.load(audio_path, sr=sr, mono=True)
    duration = librosa.get_duration(y=y, sr=sr_actual)

    # Compute beat-synchronous chroma features
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr_actual, hop_length=hop_length)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr_actual, units="frames", bpm=bpm)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr_actual)

    if len(beat_frames) < 8:
        logger.info("  Too few beats for loop detection")
        return []

    # Beat-synchronous chroma
    beat_chroma = librosa.util.sync(chroma, beat_frames, aggregate=np.median)
    n_beats = beat_chroma.shape[1]

    # Compute self-similarity matrix
    sim_matrix = _compute_similarity_matrix(beat_chroma)

    # Find repeating patterns at different loop lengths
    beat_duration = 60.0 / bpm
    loops = []

    for loop_beats in [4, 8, 16, 32]:
        if loop_beats >= n_beats:
            continue

        detected = _find_repetitions(
            sim_matrix, loop_beats, n_beats,
            beat_duration, beat_times,
        )
        loops.extend(detected)

    # Sort by confidence, deduplicate overlapping
    loops.sort(key=lambda x: x["confidence"], reverse=True)
    loops = _deduplicate_loops(loops)

    logger.info(f"  Found {len(loops)} loops")
    return loops


def _compute_similarity_matrix(beat_chroma: np.ndarray) -> np.ndarray:
    """Compute cosine similarity matrix between beat-synchronous features."""
    # Normalize columns
    norms = np.linalg.norm(beat_chroma, axis=0, keepdims=True)
    norms[norms == 0] = 1
    normalized = beat_chroma / norms

    # Cosine similarity
    sim = normalized.T @ normalized
    return sim


def _find_repetitions(
    sim_matrix: np.ndarray,
    loop_beats: int,
    n_beats: int,
    beat_duration: float,
    beat_times: np.ndarray,
) -> list[dict]:
    """Find repetitions of a specific loop length."""
    results = []
    n_possible = n_beats - loop_beats

    for start in range(0, n_possible, loop_beats):
        # Check how many times this pattern repeats
        repetitions = 0
        total_similarity = 0.0

        for rep in range(1, (n_beats - start) // loop_beats):
            rep_start = start + rep * loop_beats
            if rep_start + loop_beats > n_beats:
                break

            # Average similarity between original and this repetition
            sim_sum = 0.0
            count = 0
            for offset in range(loop_beats):
                if start + offset < n_beats and rep_start + offset < n_beats:
                    sim_sum += sim_matrix[start + offset, rep_start + offset]
                    count += 1

            avg_sim = sim_sum / max(count, 1)

            if avg_sim > 0.7:  # Threshold for "repeating"
                repetitions += 1
                total_similarity += avg_sim
            else:
                break

        if repetitions >= 2:
            confidence = total_similarity / repetitions if repetitions > 0 else 0
            start_time = float(beat_times[start]) if start < len(beat_times) else start * beat_duration
            loop_duration = loop_beats * beat_duration

            results.append({
                "start": round(start_time, 2),
                "end": round(start_time + loop_duration, 2),
                "duration": round(loop_duration, 2),
                "duration_beats": loop_beats,
                "repetitions": repetitions,
                "confidence": round(float(confidence), 3),
                "total_duration": round(loop_duration * (repetitions + 1), 2),
            })

    return results


def _deduplicate_loops(loops: list[dict], overlap_threshold: float = 0.5) -> list[dict]:
    """Remove overlapping loop detections, keeping higher confidence ones."""
    if not loops:
        return []

    kept = []
    for loop in loops:
        overlapping = False
        for existing in kept:
            overlap = _compute_overlap(loop, existing)
            if overlap > overlap_threshold:
                overlapping = True
                break
        if not overlapping:
            kept.append(loop)

    return kept


def _compute_overlap(a: dict, b: dict) -> float:
    """Compute temporal overlap ratio between two loops."""
    a_start, a_end = a["start"], a["start"] + a["total_duration"]
    b_start, b_end = b["start"], b["start"] + b["total_duration"]

    overlap_start = max(a_start, b_start)
    overlap_end = min(a_end, b_end)

    if overlap_start >= overlap_end:
        return 0.0

    overlap = overlap_end - overlap_start
    shorter = min(a_end - a_start, b_end - b_start)
    return overlap / max(shorter, 0.001)


def get_repetition_style(brand_config: Optional[dict] = None) -> str:
    """Get the configured repetition style from brand guide.

    Args:
        brand_config: Brand guide dict.

    Returns:
        One of: "evolving", "rotating", "exact", "transforming"
    """
    if not brand_config:
        return DEFAULT_REPETITION_STYLE
    rep = brand_config.get("repetition", {})
    return rep.get("style", DEFAULT_REPETITION_STYLE)


def apply_repetition_to_segments(
    segments: list[dict],
    loops: list[dict],
    brand_config: Optional[dict] = None,
) -> list[dict]:
    """Add loop/repetition metadata to segments.

    For segments that fall within detected loops, adds repetition
    metadata indicating the visual strategy.

    Args:
        segments: Pipeline segments with 'start', 'end'.
        loops: Detected loops from detect_loops().
        brand_config: Brand guide.

    Returns:
        Same segments with added 'repetition' metadata.
    """
    style = get_repetition_style(brand_config)

    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        seg_mid = (seg_start + seg_end) / 2

        for loop in loops:
            loop_start = loop["start"]
            loop_total_end = loop["start"] + loop["total_duration"]

            if loop_start <= seg_mid <= loop_total_end:
                # This segment falls within a detected loop
                # Determine which repetition number this is
                loop_dur = loop["duration"]
                if loop_dur > 0:
                    rep_index = int((seg_mid - loop_start) / loop_dur)
                else:
                    rep_index = 0

                seg["repetition"] = {
                    "in_loop": True,
                    "loop_duration_beats": loop["duration_beats"],
                    "repetition_index": rep_index,
                    "total_repetitions": loop["repetitions"],
                    "style": style,
                    "confidence": loop["confidence"],
                }

                # Add style-specific modifiers
                if style == "evolving":
                    intensity = 0.1 * rep_index  # Slight evolution per repeat
                    seg["repetition"]["evolution_intensity"] = round(min(1.0, intensity), 2)
                elif style == "rotating":
                    hue_shift = (rep_index * 30) % 360
                    seg["repetition"]["hue_rotation"] = hue_shift
                elif style == "exact":
                    seg["repetition"]["reuse_keyframe"] = True
                elif style == "transforming":
                    morph = min(1.0, rep_index / max(loop["repetitions"], 1))
                    seg["repetition"]["morph_progress"] = round(morph, 2)

                break  # Only match first loop

    return segments
