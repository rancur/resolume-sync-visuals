"""
Drop prediction and buildup-aware visual anticipation.

Analyzes phrase sequences to identify buildup->drop transitions
and generates anticipation metadata so visuals can progressively
shift toward the drop's visual style during the final beats of
a buildup. Breakdowns similarly foreshadow the next section.

The anticipation window is configurable via brand guide:
  anticipation:
    beats: 8          # How many beats before the drop to start shifting
    intensity: 0.7    # How much to blend toward the drop style (0-1)
    breakdown_beats: 4 # Beats before next section in breakdowns
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_ANTICIPATION_BEATS = 8
DEFAULT_ANTICIPATION_INTENSITY = 0.7
DEFAULT_BREAKDOWN_ANTICIPATION_BEATS = 4


def get_anticipation_config(brand_config: Optional[dict] = None) -> dict:
    """Extract anticipation config from brand guide.

    Args:
        brand_config: Brand guide dict. Looks for 'anticipation' key.

    Returns:
        Config dict with beats, intensity, breakdown_beats.
    """
    if not brand_config:
        return {
            "beats": DEFAULT_ANTICIPATION_BEATS,
            "intensity": DEFAULT_ANTICIPATION_INTENSITY,
            "breakdown_beats": DEFAULT_BREAKDOWN_ANTICIPATION_BEATS,
        }

    antic = brand_config.get("anticipation", {})
    return {
        "beats": antic.get("beats", DEFAULT_ANTICIPATION_BEATS),
        "intensity": antic.get("intensity", DEFAULT_ANTICIPATION_INTENSITY),
        "breakdown_beats": antic.get("breakdown_beats", DEFAULT_BREAKDOWN_ANTICIPATION_BEATS),
    }


def find_transitions(phrases: list[dict]) -> list[dict]:
    """Identify buildup->drop and breakdown->next transitions.

    Args:
        phrases: List of phrase dicts with at least 'label', 'start', 'end',
                 'energy', and optionally 'beats'.

    Returns:
        List of transition dicts:
        {
            "type": "buildup_to_drop" | "breakdown_to_next",
            "from_index": int,
            "to_index": int,
            "from_label": str,
            "to_label": str,
            "from_energy": float,
            "to_energy": float,
            "energy_jump": float,
        }
    """
    transitions = []

    for i in range(len(phrases) - 1):
        current = phrases[i]
        next_p = phrases[i + 1]
        c_label = current.get("label", "").lower()
        n_label = next_p.get("label", "").lower()
        c_energy = current.get("energy", 0.5)
        n_energy = next_p.get("energy", 0.5)

        if c_label == "buildup" and n_label == "drop":
            transitions.append({
                "type": "buildup_to_drop",
                "from_index": i,
                "to_index": i + 1,
                "from_label": c_label,
                "to_label": n_label,
                "from_energy": c_energy,
                "to_energy": n_energy,
                "energy_jump": n_energy - c_energy,
            })
        elif c_label == "breakdown" and n_label in ("buildup", "drop"):
            transitions.append({
                "type": "breakdown_to_next",
                "from_index": i,
                "to_index": i + 1,
                "from_label": c_label,
                "to_label": n_label,
                "from_energy": c_energy,
                "to_energy": n_energy,
                "energy_jump": n_energy - c_energy,
            })

    return transitions


def apply_anticipation(
    segments: list[dict],
    bpm: float,
    brand_config: Optional[dict] = None,
) -> list[dict]:
    """Add anticipation metadata to segments approaching drops.

    For each buildup->drop transition, the buildup segment gets an
    'anticipation' field describing how its tail should shift toward
    the drop's visual characteristics.

    For breakdown->next transitions, a lighter anticipation is applied.

    Args:
        segments: List of segment dicts (from pipeline _plan_segments).
                  Each must have 'label', 'start', 'end', 'energy', 'prompt'.
        bpm: Track BPM (to calculate anticipation window in seconds).
        brand_config: Optional brand guide for config overrides.

    Returns:
        Same segments list with 'anticipation' field added where applicable.
        Does NOT mutate prompts -- downstream code uses the anticipation
        metadata to adjust generation parameters.
    """
    config = get_anticipation_config(brand_config)
    antic_beats = config["beats"]
    antic_intensity = config["intensity"]
    breakdown_beats = config["breakdown_beats"]

    beat_duration = 60.0 / bpm if bpm > 0 else 0.5

    transitions = find_transitions(segments)

    for trans in transitions:
        from_idx = trans["from_index"]
        to_idx = trans["to_index"]
        from_seg = segments[from_idx]
        to_seg = segments[to_idx]

        if trans["type"] == "buildup_to_drop":
            window_beats = antic_beats
            intensity = antic_intensity
        else:
            window_beats = breakdown_beats
            intensity = antic_intensity * 0.5  # Lighter for breakdowns

        window_seconds = window_beats * beat_duration
        seg_duration = from_seg["end"] - from_seg["start"]

        # Don't apply if segment is shorter than the window
        if seg_duration < window_seconds * 0.5:
            continue

        # Clamp window to segment duration
        actual_window = min(window_seconds, seg_duration * 0.75)
        anticipation_start = from_seg["end"] - actual_window

        from_seg["anticipation"] = {
            "target_label": to_seg["label"],
            "target_energy": to_seg["energy"],
            "target_prompt": to_seg.get("prompt", ""),
            "window_beats": window_beats,
            "window_seconds": round(actual_window, 2),
            "anticipation_start": round(anticipation_start, 2),
            "blend_intensity": round(intensity, 2),
            "energy_jump": round(trans["energy_jump"], 3),
            "transition_type": trans["type"],
        }

        logger.info(
            f"  Anticipation: segment {from_idx} ({from_seg['label']}) "
            f"-> segment {to_idx} ({to_seg['label']}), "
            f"window={actual_window:.1f}s, intensity={intensity:.2f}"
        )

    return segments


def build_anticipation_prompt_modifier(
    anticipation: dict,
    progress: float = 0.5,
) -> str:
    """Build a prompt modifier for the anticipation window.

    As progress goes from 0.0 (start of anticipation) to 1.0 (drop),
    the modifier shifts from subtle foreshadowing to strong preview.

    Args:
        anticipation: Anticipation dict from apply_anticipation().
        progress: 0.0-1.0, how far into the anticipation window.

    Returns:
        Prompt modifier string to append to the segment's prompt.
    """
    progress = max(0.0, min(1.0, progress))
    intensity = anticipation.get("blend_intensity", 0.7)
    target_label = anticipation.get("target_label", "drop")
    energy_jump = anticipation.get("energy_jump", 0.3)
    transition_type = anticipation.get("transition_type", "buildup_to_drop")

    # Scale intensity by progress (exponential for more dramatic buildup)
    effective_intensity = intensity * (progress ** 1.5)

    parts = []

    if transition_type == "buildup_to_drop":
        if progress < 0.3:
            parts.append("subtle visual tension building")
            parts.append("colors beginning to shift")
        elif progress < 0.6:
            parts.append("visual intensity ramping up")
            parts.append("increasing visual complexity and energy")
            parts.append("color palette shifting toward peak intensity")
        elif progress < 0.85:
            parts.append("strong visual anticipation")
            parts.append("nearly at peak visual intensity")
            parts.append("colors and motion previewing the incoming peak")
        else:
            parts.append("maximum pre-drop tension")
            parts.append("visual explosion imminent")
            parts.append("all elements converging toward peak energy")
    else:
        # Breakdown to next
        if progress < 0.5:
            parts.append("gentle visual hint of returning energy")
        else:
            parts.append("visual elements slowly reawakening")
            parts.append("subtle foreshadowing of incoming intensity")

    # Add energy-based modifier
    if energy_jump > 0.3:
        parts.append("dramatic energy contrast approaching")
    elif energy_jump > 0.15:
        parts.append("building toward higher energy")

    return ", ".join(parts)


def compute_anticipation_motion_boost(
    anticipation: dict,
    progress: float,
    base_motion: int = 5,
) -> int:
    """Compute boosted motion value during anticipation window.

    Gradually increases motion toward the drop's expected intensity.

    Args:
        anticipation: Anticipation dict from apply_anticipation().
        progress: 0.0-1.0, how far into the anticipation window.
        base_motion: Current segment's base motion value.

    Returns:
        Boosted motion value (integer).
    """
    progress = max(0.0, min(1.0, progress))
    intensity = anticipation.get("blend_intensity", 0.7)
    target_energy = anticipation.get("target_energy", 0.9)

    # Target motion based on drop energy
    target_motion = max(base_motion, int(2 + target_energy * 8))

    # Blend based on progress (exponential curve)
    boost = (target_motion - base_motion) * intensity * (progress ** 2.0)

    return min(10, max(base_motion, round(base_motion + boost)))
