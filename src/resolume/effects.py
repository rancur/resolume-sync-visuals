"""
Resolume Arena Effect Automation.
Issue #43: Effect automation tied to song sections in .avc.

Generates effect automation keyframes for Resolume compositions
based on song section analysis.
"""
import logging
import xml.etree.ElementTree as ET
from typing import Optional

logger = logging.getLogger(__name__)

# Resolume effect parameter IDs
EFFECT_PARAMS = {
    "contrast": {
        "effect_name": "Contrast",
        "param_name": "Contrast",
        "min": 0.0,
        "max": 2.0,
        "default": 1.0,
    },
    "blur": {
        "effect_name": "GaussianBlur",
        "param_name": "Amount",
        "min": 0.0,
        "max": 1.0,
        "default": 0.0,
    },
    "saturation": {
        "effect_name": "HSL",
        "param_name": "Saturation",
        "min": 0.0,
        "max": 2.0,
        "default": 1.0,
    },
    "zoom": {
        "effect_name": "Zoom",
        "param_name": "Zoom",
        "min": 0.5,
        "max": 2.0,
        "default": 1.0,
    },
    "speed": {
        "effect_name": "Transport",
        "param_name": "Speed",
        "min": 0.0,
        "max": 4.0,
        "default": 1.0,
    },
    "strobe_rate": {
        "effect_name": "Strobe",
        "param_name": "Rate",
        "min": 0.0,
        "max": 1.0,
        "default": 0.0,
    },
    "brightness": {
        "effect_name": "Brightness",
        "param_name": "Brightness",
        "min": 0.0,
        "max": 2.0,
        "default": 1.0,
    },
    "hue_rotate": {
        "effect_name": "HSL",
        "param_name": "Hue",
        "min": 0.0,
        "max": 1.0,
        "default": 0.0,
    },
}

# Default section effect profiles
DEFAULT_SECTION_PROFILES = {
    "intro": {
        "contrast": 0.9,
        "saturation": 0.7,
        "blur": 0.15,
        "brightness": 0.8,
    },
    "buildup": {
        "contrast": 1.1,
        "saturation": 1.0,
        "zoom": {"start": 1.0, "end": 1.3},
        "brightness": 1.1,
    },
    "drop": {
        "contrast": 1.5,
        "strobe_rate": 0.25,
        "saturation": 1.3,
        "brightness": 1.3,
    },
    "breakdown": {
        "blur": 0.4,
        "saturation": 0.6,
        "speed": 0.5,
        "brightness": 0.9,
    },
    "outro": {
        "contrast": 0.8,
        "saturation": 0.5,
        "blur": 0.3,
        "brightness": 0.6,
    },
}


def generate_effect_keyframes(
    sections: list[dict],
    profiles: Optional[dict] = None,
    smooth_transitions: bool = True,
    transition_beats: int = 4,
    bpm: float = 128.0,
) -> list[dict]:
    """
    Generate effect automation keyframes from song sections.

    Args:
        sections: List of section dicts with keys:
            - label: str (intro, buildup, drop, breakdown, outro)
            - start_time: float (seconds)
            - end_time: float (seconds)
        profiles: Optional override for section effect profiles.
            Falls back to DEFAULT_SECTION_PROFILES.
        smooth_transitions: If True, generate smooth ramps between sections.
        transition_beats: Number of beats for transition ramps.
        bpm: Track BPM for calculating transition duration.

    Returns:
        List of keyframe dicts with:
            - time: float (seconds)
            - effect: str (effect param name)
            - value: float
            - interpolation: str (linear, ease_in, ease_out, step)
    """
    profiles = profiles or DEFAULT_SECTION_PROFILES
    keyframes = []
    beat_duration = 60.0 / bpm
    transition_duration = transition_beats * beat_duration

    for i, section in enumerate(sections):
        label = section.get("label", "intro")
        start = section.get("start_time", 0.0)
        end = section.get("end_time", start + 30.0)
        profile = profiles.get(label, {})

        for param_name, value in profile.items():
            if isinstance(value, dict):
                # Ramped parameter (e.g., zoom: {start: 1.0, end: 1.3})
                start_val = value.get("start", EFFECT_PARAMS.get(param_name, {}).get("default", 0))
                end_val = value.get("end", start_val)
                keyframes.append({
                    "time": start,
                    "effect": param_name,
                    "value": start_val,
                    "interpolation": "linear",
                })
                keyframes.append({
                    "time": end,
                    "effect": param_name,
                    "value": end_val,
                    "interpolation": "linear",
                })
            else:
                # Static value for this section
                if smooth_transitions and i > 0:
                    # Ramp from previous section's value
                    keyframes.append({
                        "time": max(0, start - transition_duration),
                        "effect": param_name,
                        "value": _get_prev_value(sections, i - 1, param_name, profiles),
                        "interpolation": "ease_out",
                    })
                keyframes.append({
                    "time": start,
                    "effect": param_name,
                    "value": float(value),
                    "interpolation": "ease_in" if smooth_transitions else "step",
                })

    # Sort by time
    keyframes.sort(key=lambda k: (k["time"], k["effect"]))
    return keyframes


def _get_prev_value(
    sections: list[dict],
    prev_idx: int,
    param_name: str,
    profiles: dict,
) -> float:
    """Get the value of a param from the previous section."""
    if prev_idx < 0:
        return EFFECT_PARAMS.get(param_name, {}).get("default", 0)
    prev_label = sections[prev_idx].get("label", "intro")
    prev_profile = profiles.get(prev_label, {})
    val = prev_profile.get(param_name, EFFECT_PARAMS.get(param_name, {}).get("default", 0))
    if isinstance(val, dict):
        return val.get("end", val.get("start", 0))
    return float(val)


def inject_effects_into_avc(
    avc_xml: str,
    keyframes: list[dict],
    layer_index: int = 0,
) -> str:
    """
    Inject effect automation keyframes into an existing .avc XML string.

    Args:
        avc_xml: The existing .avc XML content
        keyframes: Effect keyframes from generate_effect_keyframes()
        layer_index: Which layer to attach effects to

    Returns:
        Modified .avc XML string with effect automations
    """
    root = ET.fromstring(avc_xml)

    # Find the target layer (or deck)
    # Support both composition and arena root elements
    effects_by_param = {}
    for kf in keyframes:
        param = kf["effect"]
        if param not in effects_by_param:
            effects_by_param[param] = []
        effects_by_param[param].append(kf)

    # Build automation XML block
    automation_comment = ET.Comment(
        " Effect automations generated by RSV "
    )

    # Find or create effects container
    for elem_tag in ["Deck", "Layer", "Composition", "composition"]:
        targets = root.findall(f".//{elem_tag}")
        if targets:
            target = targets[min(layer_index, len(targets) - 1)]

            effects_elem = target.find("VideoEffectChain")
            if effects_elem is None:
                effects_elem = ET.SubElement(target, "VideoEffectChain", name="VideoEffectChain")

            for param_name, kfs in effects_by_param.items():
                if param_name not in EFFECT_PARAMS:
                    continue

                ep = EFFECT_PARAMS[param_name]
                effect = ET.SubElement(
                    effects_elem, "VideoEffect",
                    name=ep["effect_name"],
                    enabled="1",
                )
                params = ET.SubElement(effect, "Params", name="Params")
                param_range = ET.SubElement(
                    params, "ParamRange",
                    name=ep["param_name"],
                    T="DOUBLE",
                    default=str(ep["default"]),
                    value=str(kfs[0]["value"] if kfs else ep["default"]),
                )

                # Add automation keyframes
                automation = ET.SubElement(param_range, "Automation", name="Automation")
                for kf in kfs:
                    ET.SubElement(
                        automation, "Key",
                        time=f"{kf['time']:.3f}",
                        value=str(kf["value"]),
                        interpolation=kf.get("interpolation", "linear"),
                    )

            break

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def get_section_profiles() -> dict:
    """Return the current default section effect profiles."""
    return DEFAULT_SECTION_PROFILES.copy()


def get_available_effects() -> list[dict]:
    """Return list of available effects with their parameter ranges."""
    return [
        {
            "id": param_id,
            "name": info["effect_name"],
            "param": info["param_name"],
            "min": info["min"],
            "max": info["max"],
            "default": info["default"],
        }
        for param_id, info in EFFECT_PARAMS.items()
    ]
