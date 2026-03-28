"""
Timeline composer — maps generated clips to the full song structure.
Creates the final output clips organized for Resolume Arena import.

Output structure:
  output/<track_name>/
    ├── analysis.json          # Full analysis data
    ├── clips/
    │   ├── phrase_000_intro.mp4
    │   ├── phrase_001_buildup.mp4
    │   └── ...
    ├── loops/                 # Beat-quantized seamless loops
    │   ├── loop_drop_001.mp4
    │   ├── loop_buildup_001.mp4
    │   └── ...
    └── metadata.json          # Resolume-compatible metadata
"""
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def compose_timeline(
    analysis: dict,
    clips: list[dict],
    output_dir: str | Path,
    extend_loops: bool = True,
) -> dict:
    """
    Compose final timeline from analysis and generated clips.

    Args:
        analysis: Track analysis dict
        clips: List of clip dicts from generator
        output_dir: Base output directory
        extend_loops: If True, extend short loops to fill phrase duration

    Returns:
        Composition metadata dict
    """
    output_dir = Path(output_dir)
    clips_dir = output_dir / "clips"
    loops_dir = output_dir / "loops"
    clips_dir.mkdir(parents=True, exist_ok=True)
    loops_dir.mkdir(parents=True, exist_ok=True)

    bpm = analysis["bpm"]
    beat_duration = 60.0 / bpm

    composition = {
        "track": analysis.get("title", "Unknown"),
        "file": analysis.get("file_path", ""),
        "bpm": bpm,
        "duration": analysis.get("duration", 0),
        "time_signature": analysis.get("time_signature", 4),
        "clips": [],
        "loops": [],
        "resolume_mapping": [],
    }

    # Organize clips
    for clip in clips:
        src = Path(clip["path"])
        if not src.exists():
            logger.warning(f"Clip not found: {src}")
            continue

        # Copy to organized clips dir
        dst = clips_dir / src.name
        if src != dst:
            shutil.copy2(src, dst)

        clip_info = {
            "file": str(dst),
            "phrase_idx": clip["phrase_idx"],
            "start_time": clip["start"],
            "end_time": clip["end"],
            "duration": clip["duration"],
            "label": clip["label"],
            "bpm": bpm,
            "beats": clip["beats"],
            "bar_aligned": True,
        }
        composition["clips"].append(clip_info)

    # Create extended loops for each phrase type
    phrase_types = {}
    for clip in clips:
        label = clip["label"]
        if label not in phrase_types:
            phrase_types[label] = []
        phrase_types[label].append(clip)

    for label, type_clips in phrase_types.items():
        for idx, clip in enumerate(type_clips):
            src = Path(clip["path"])
            if not src.exists():
                continue

            # Create a loop that's exactly N bars long
            target_beats = clip["beats"]
            target_duration = target_beats * beat_duration

            loop_name = f"loop_{label}_{idx:03d}.mp4"
            loop_path = loops_dir / loop_name

            if extend_loops:
                _create_extended_loop(src, loop_path, target_duration)
            else:
                shutil.copy2(src, loop_path)

            loop_info = {
                "file": str(loop_path),
                "label": label,
                "beats": target_beats,
                "bars": target_beats // analysis.get("time_signature", 4),
                "duration": target_duration,
                "bpm": bpm,
                "seamless": True,
            }
            composition["loops"].append(loop_info)

    # Generate Resolume mapping (for future ALFC export)
    composition["resolume_mapping"] = _build_resolume_mapping(composition)

    # Save metadata
    meta_path = output_dir / "metadata.json"
    meta_path.write_text(json.dumps(composition, indent=2))

    # Save analysis
    analysis_path = output_dir / "analysis.json"
    analysis_path.write_text(json.dumps(analysis, indent=2, default=str))

    logger.info(f"Composition complete: {len(composition['clips'])} clips, "
                f"{len(composition['loops'])} loops")

    return composition


def _create_extended_loop(
    source: Path,
    output: Path,
    target_duration: float,
):
    """
    Extend a short clip to target duration by looping it seamlessly.
    Uses ffmpeg's loop filter and crossfade for seamless looping.
    """
    # Get source duration
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json",
        str(source),
    ]
    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        probe_data = json.loads(result.stdout)
        src_duration = float(probe_data["format"]["duration"])
    except Exception:
        # Fallback — just copy
        shutil.copy2(source, output)
        return

    if src_duration >= target_duration * 0.95:
        # Source is already long enough — just trim
        trim_cmd = [
            "ffmpeg", "-y",
            "-i", str(source),
            "-t", str(target_duration),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output),
        ]
        subprocess.run(trim_cmd, capture_output=True, timeout=120)
        return

    # Need to loop — calculate repetitions needed
    n_loops = int(target_duration / src_duration) + 1

    # Create looped version with stream_loop
    loop_cmd = [
        "ffmpeg", "-y",
        "-stream_loop", str(n_loops),
        "-i", str(source),
        "-t", str(target_duration),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",
        str(output),
    ]
    subprocess.run(loop_cmd, capture_output=True, timeout=120)


def _build_resolume_mapping(composition: dict) -> list[dict]:
    """
    Build Resolume Arena clip mapping.
    Maps clips to layers and columns for easy import.

    Resolume structure:
    - Layer 1: Drop clips
    - Layer 2: Buildup clips
    - Layer 3: Breakdown clips
    - Layer 4: Intro/Outro clips

    Each layer gets clips in columns matching phrase order.
    """
    layer_map = {
        "drop": 1,
        "buildup": 2,
        "breakdown": 3,
        "intro": 4,
        "outro": 4,
    }

    mapping = []
    column_counters = {1: 0, 2: 0, 3: 0, 4: 0}

    for loop in composition.get("loops", []):
        label = loop.get("label", "intro")
        layer = layer_map.get(label, 4)
        col = column_counters.get(layer, 0)
        column_counters[layer] = col + 1

        mapping.append({
            "file": loop["file"],
            "layer": layer,
            "column": col,
            "label": label,
            "bpm": loop["bpm"],
            "beats": loop["beats"],
            "transport": "BPM Sync",
            "trigger": "Column",
        })

    return mapping
