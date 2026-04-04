"""
Rich metadata generation for track visual generation.

Produces a comprehensive JSON metadata file alongside each generated video,
capturing track info, phrase timeline, energy curves, mood analysis,
per-segment generation details, stem analysis, and cost breakdowns.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def generate_track_metadata(
    analysis: dict,
    mood: Optional[dict] = None,
    sonic_timeline: Optional[dict] = None,
    generation_info: Optional[dict] = None,
) -> dict:
    """Generate rich metadata JSON for a track's visual generation.

    Includes:
    - Track info (title, artist, BPM, duration, genre, key)
    - Phrase timeline with timestamps and labels
    - Energy curve (per-beat energy values)
    - Mood analysis (valence, arousal, quadrant)
    - Per-segment generation details (keyframe prompt, model, cost)
    - Stem analysis summary (drums/bass/synth/vocal energy per phrase)
    - Total cost breakdown

    Args:
        analysis: Track analysis dict with at minimum {title, artist, bpm, duration}.
                  May include phrases, energy_curve, stems, genre, key.
        mood: Optional mood analysis dict with valence, arousal, quadrant, tags.
        sonic_timeline: Optional dict with per-beat or per-phrase sonic features.
        generation_info: Optional dict with segments list, model, total_cost, etc.

    Returns:
        A structured metadata dict ready to be saved as JSON.
    """
    metadata = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "track": _extract_track_info(analysis),
        "phrase_timeline": _extract_phrase_timeline(analysis),
        "energy_curve": _extract_energy_curve(analysis, sonic_timeline),
        "mood": _extract_mood(mood),
        "segments": _extract_segments(generation_info),
        "stems": _extract_stems(analysis, sonic_timeline),
        "cost_breakdown": _extract_cost_breakdown(generation_info),
    }

    return metadata


def save_metadata(metadata: dict, output_path: Path) -> Path:
    """Save metadata dict as a JSON file.

    Args:
        metadata: The metadata dict from generate_track_metadata().
        output_path: Path to write the JSON file (typically metadata.json).

    Returns:
        The output_path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    logger.info("Saved track metadata to %s", output_path)
    return output_path


def _extract_track_info(analysis: dict) -> dict:
    """Extract core track info from analysis."""
    return {
        "title": analysis.get("title", "Unknown"),
        "artist": analysis.get("artist", "Unknown"),
        "bpm": analysis.get("bpm", 0),
        "duration": analysis.get("duration", 0),
        "genre": analysis.get("genre", ""),
        "key": analysis.get("key", ""),
    }


def _extract_phrase_timeline(analysis: dict) -> list:
    """Extract phrase/section timeline from analysis.

    Each entry has: start, end, duration, label, energy.
    """
    phrases = analysis.get("phrases", analysis.get("sections", []))
    timeline = []
    for p in phrases:
        entry = {
            "start": p.get("start", p.get("start_time", 0)),
            "end": p.get("end", p.get("end_time", 0)),
            "duration": p.get("duration", 0),
            "label": p.get("label", p.get("type", "unknown")),
            "energy": p.get("energy", 0.5),
        }
        # Compute duration if not set
        if entry["duration"] == 0 and entry["end"] > entry["start"]:
            entry["duration"] = entry["end"] - entry["start"]
        timeline.append(entry)
    return timeline


def _extract_energy_curve(analysis: dict, sonic_timeline: Optional[dict]) -> list:
    """Extract energy curve data.

    Returns list of {time, energy} points for graphing.
    """
    # Try sonic_timeline first
    if sonic_timeline and "energy_curve" in sonic_timeline:
        return sonic_timeline["energy_curve"]

    # Try analysis
    if "energy_curve" in analysis:
        return analysis["energy_curve"]

    # Build from phrases
    phrases = analysis.get("phrases", analysis.get("sections", []))
    if not phrases:
        return []

    curve = []
    for p in phrases:
        start = p.get("start", p.get("start_time", 0))
        end = p.get("end", p.get("end_time", 0))
        energy = p.get("energy", 0.5)
        curve.append({"time": start, "energy": energy})
        curve.append({"time": end, "energy": energy})
    return curve


def _extract_mood(mood: Optional[dict]) -> dict:
    """Extract mood analysis info."""
    if not mood:
        return {"valence": 0.5, "arousal": 0.5, "quadrant": "neutral", "tags": []}

    return {
        "valence": mood.get("valence", mood.get("happiness", 0.5)),
        "arousal": mood.get("arousal", mood.get("energy", 0.5)),
        "quadrant": mood.get("quadrant", mood.get("mood_quadrant", "neutral")),
        "tags": mood.get("tags", mood.get("mood_tags", [])),
    }


def _extract_segments(generation_info: Optional[dict]) -> list:
    """Extract per-segment generation details."""
    if not generation_info:
        return []

    segments = generation_info.get("segments", [])
    result = []
    for seg in segments:
        result.append({
            "index": seg.get("index", seg.get("idx", 0)),
            "label": seg.get("label", seg.get("phrase_label", "")),
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
            "prompt": seg.get("prompt", seg.get("keyframe_prompt", "")),
            "model": seg.get("model", generation_info.get("model", "")),
            "cost": seg.get("cost", 0),
            "cached": seg.get("cached", False),
            "video_path": seg.get("video_path", ""),
        })
    return result


def _extract_stems(analysis: dict, sonic_timeline: Optional[dict]) -> dict:
    """Extract stem analysis summary."""
    stems_data = {}
    if sonic_timeline and "stems" in sonic_timeline:
        stems_data = sonic_timeline["stems"]
    elif "stems" in analysis:
        stems_data = analysis["stems"]

    if not stems_data:
        return {"available": False}

    return {
        "available": True,
        "drums": stems_data.get("drums", {}),
        "bass": stems_data.get("bass", {}),
        "vocals": stems_data.get("vocals", stems_data.get("vocal", {})),
        "other": stems_data.get("other", stems_data.get("synth", {})),
    }


def _extract_cost_breakdown(generation_info: Optional[dict]) -> dict:
    """Extract cost breakdown from generation info."""
    if not generation_info:
        return {"total": 0, "keyframes": 0, "video": 0, "model": ""}

    return {
        "total": generation_info.get("total_cost", 0),
        "keyframes": generation_info.get("keyframe_cost", 0),
        "video": generation_info.get("video_cost", 0),
        "model": generation_info.get("model", ""),
        "quality": generation_info.get("quality", ""),
        "duration_secs": generation_info.get("duration_secs", 0),
    }
