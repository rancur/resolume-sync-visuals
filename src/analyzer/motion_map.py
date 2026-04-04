"""
Motion intensity mapping from audio energy envelope.

Maps per-segment energy values to video generation motion parameters
(e.g., Kling's motion_amount, camera speed, crossfade intensity).
"""
import math
from typing import Literal

# Motion mapping config defaults
DEFAULT_MOTION_FLOOR = 2
DEFAULT_MOTION_CEILING = 9
DEFAULT_CURVE = "exponential"


def energy_to_motion(
    energy: float,
    floor: int = DEFAULT_MOTION_FLOOR,
    ceiling: int = DEFAULT_MOTION_CEILING,
    curve: Literal["linear", "exponential", "logarithmic"] = DEFAULT_CURVE,
) -> int:
    """
    Map a normalized energy value (0.0 - 1.0) to a motion intensity value.

    Args:
        energy: Normalized energy (0.0 = silence, 1.0 = max energy).
        floor: Minimum motion value (even for silent sections).
        ceiling: Maximum motion value (for peak energy).
        curve: Mapping curve type.

    Returns:
        Integer motion intensity between floor and ceiling.
    """
    # Clamp energy to [0, 1]
    e = max(0.0, min(1.0, energy))

    if curve == "linear":
        mapped = e
    elif curve == "exponential":
        # Exponential: low energy stays subdued, high energy really pops
        mapped = e ** 2.0
    elif curve == "logarithmic":
        # Logarithmic: quick ramp at low energy, gentle at high
        mapped = math.log1p(e * (math.e - 1)) / 1.0
    else:
        mapped = e

    value = floor + mapped * (ceiling - floor)
    return max(floor, min(ceiling, round(value)))


def energy_to_crossfade(
    energy: float,
    min_duration: float = 0.5,
    max_duration: float = 3.0,
    curve: Literal["linear", "exponential", "logarithmic"] = "exponential",
) -> float:
    """
    Map energy to crossfade duration.

    High energy = short/hard cuts. Low energy = long/smooth fades.
    This is INVERSE mapping (high energy -> short duration).

    Args:
        energy: Normalized energy (0.0 - 1.0).
        min_duration: Shortest crossfade (at peak energy).
        max_duration: Longest crossfade (at low energy).
        curve: Mapping curve.

    Returns:
        Crossfade duration in seconds.
    """
    e = max(0.0, min(1.0, energy))

    if curve == "exponential":
        mapped = e ** 2.0
    elif curve == "logarithmic":
        mapped = math.log1p(e * (math.e - 1)) / 1.0
    else:
        mapped = e

    # Inverse: high energy -> short duration
    duration = max_duration - mapped * (max_duration - min_duration)
    return round(max(min_duration, min(max_duration, duration)), 2)


def map_segments_to_motion(
    segments: list[dict],
    floor: int = DEFAULT_MOTION_FLOOR,
    ceiling: int = DEFAULT_MOTION_CEILING,
    curve: Literal["linear", "exponential", "logarithmic"] = DEFAULT_CURVE,
) -> list[dict]:
    """
    Add motion_amount and crossfade_duration to each segment based on energy.

    Args:
        segments: List of segment dicts with at least {"energy": float} field.
        floor: Min motion value.
        ceiling: Max motion value.
        curve: Mapping curve.

    Returns:
        Same segments with added "motion_amount" and "crossfade_duration" fields.
    """
    for seg in segments:
        energy = seg.get("energy", 0.5)
        # Normalize if energy is 0-10 scale
        if energy > 1.0:
            energy = energy / 10.0
        seg["motion_amount"] = energy_to_motion(energy, floor, ceiling, curve)
        seg["crossfade_duration"] = energy_to_crossfade(energy, curve=curve)
    return segments


def get_motion_config(brand_config: dict) -> dict:
    """
    Extract motion mapping config from a brand configuration.

    Looks for:
        brand_config.motion_mapping.floor
        brand_config.motion_mapping.ceiling
        brand_config.motion_mapping.curve
    """
    mm = brand_config.get("motion_mapping", {})
    return {
        "floor": mm.get("floor", DEFAULT_MOTION_FLOOR),
        "ceiling": mm.get("ceiling", DEFAULT_MOTION_CEILING),
        "curve": mm.get("curve", DEFAULT_CURVE),
    }
