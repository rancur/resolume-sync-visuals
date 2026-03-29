"""
Sonic-to-Visual Mapper.

Translates sonic event timeline data into visual prompt modifiers
and per-segment descriptions that tell the AI video model exactly
what's happening musically at each moment.

Instead of just "this is a drop", we now say:
"explosive drop with heavy kick pattern, gritty synth stab hitting
every 3 beats, bass wobble intensifying, vocal chop at 0:47"

This drives dramatically more music-reactive visuals.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Map stem event types to visual descriptions
STEM_VISUAL_LANGUAGE = {
    "drums": {
        "transient": "sharp percussive impact, pixel shatter",
        "stab": "rhythmic drum burst, screen pulse",
        "onset": "drum pattern entering, rhythmic energy building",
        "sustained": "driving drum pattern, steady percussive pulse",
        "buildup": "accelerating drum roll, building rhythmic intensity",
        "drop": "massive drum impact, explosive percussion",
        "silence": "drums dropping out, sudden rhythmic void",
    },
    "bass": {
        "transient": "bass spike, ground-shaking low frequency hit",
        "stab": "bass stab, heavy sub impact",
        "onset": "bass entering the mix, deep frequency rumble beginning",
        "sustained": "deep sustained bass drone, heavy low-end presence",
        "buildup": "bass building pressure, sub frequencies rising",
        "drop": "MASSIVE bass drop, earth-shattering low end",
        "silence": "bass dropping out, weightless moment",
    },
    "other": {  # synths, FX
        "transient": "sharp synth hit, electronic spike",
        "stab": "synth stab cutting through, electronic burst",
        "onset": "synth entering the mix, new melodic element appearing",
        "sustained": "sustained synth pad, atmospheric electronic texture",
        "buildup": "synth riser building, electronic tension escalating",
        "drop": "synth explosion, full electronic energy unleashed",
        "silence": "synths dropping out, electronic elements clearing",
        # Spectral character modifiers
        "gritty": "dirty distorted synth, harsh textured growl",
        "bright": "shimmering bright synth, crystalline high frequencies",
        "dark": "deep dark synth, ominous low-frequency pad",
        "clean": "clean smooth synth, polished electronic tone",
        "noisy": "noise-heavy synth, chaotic textured distortion",
    },
    "vocals": {
        "transient": "vocal chop, sharp voice cut",
        "stab": "vocal stab, quick voice sample",
        "onset": "vocals entering, voice appearing in the mix",
        "sustained": "sustained vocal, singing or spoken word",
        "buildup": "vocal building, voice intensifying",
        "silence": "vocals dropping out, voice disappearing",
    },
}

# Eye behavior mapped to sonic events (Will See specific but templatable)
EYE_REACTIONS = {
    "drums_transient": "eyes flash open on impact",
    "drums_drop": "all eyes snap wide open simultaneously",
    "drums_silence": "eyes freeze, stunned stillness",
    "bass_drop": "giant cosmic eye dilates, iris expands",
    "bass_sustained": "eyes pulse slowly with bass rhythm",
    "bass_silence": "eyes narrow, anticipating",
    "other_stab": "eyes glitch and fragment on synth stab",
    "other_gritty": "eyes distort with gritty texture, pixel corruption in iris",
    "other_buildup": "eyes multiply and spin, kaleidoscopic acceleration",
    "other_bright": "eyes glow brighter, radiant iris",
    "other_silence": "eyes slowly close, dreaming",
    "vocals_onset": "third eye opens above the scene",
    "vocals_sustained": "eyes reflect the vocal emotion",
}


@dataclass
class SegmentSonicProfile:
    """Sonic profile for one video segment, derived from stem analysis."""
    start_time: float
    end_time: float
    duration: float

    # Per-stem energy averages for this segment
    drums_energy: float = 0.0
    bass_energy: float = 0.0
    synth_energy: float = 0.0
    vocals_energy: float = 0.0

    # Dominant stem (what's loudest)
    dominant_stem: str = "drums"

    # Key sonic events in this segment
    events_summary: str = ""
    event_count: int = 0

    # Sonic character
    has_vocal: bool = False
    has_synth_stab: bool = False
    has_bass_drop: bool = False
    has_drum_break: bool = False
    has_riser: bool = False
    has_silence_moment: bool = False

    # Spectral character of synths in this segment
    synth_character: str = "clean"  # bright/dark/gritty/clean/noisy

    # Visual prompt additions
    sonic_prompt: str = ""
    eye_prompt: str = ""


def analyze_segment_sonics(
    timeline: dict,
    start_time: float,
    end_time: float,
    brand_config: Optional[dict] = None,
) -> SegmentSonicProfile:
    """
    Analyze sonic events in a time range and produce visual prompt modifiers.

    Args:
        timeline: Full event timeline from create_event_timeline()
        start_time: Segment start in seconds
        end_time: Segment end in seconds
        brand_config: Optional brand YAML for brand-specific reactions

    Returns:
        SegmentSonicProfile with visual prompt additions
    """
    profile = SegmentSonicProfile(
        start_time=start_time,
        end_time=end_time,
        duration=end_time - start_time,
    )

    events = timeline.get("events", [])
    per_frame = timeline.get("per_frame_data", {})
    fps = per_frame.get("fps", 30)

    # Filter events to this segment's time range
    segment_events = [
        e for e in events
        if start_time <= e["time"] < end_time
    ]
    profile.event_count = len(segment_events)

    # Compute per-stem energy averages for this segment
    start_frame = int(start_time * fps)
    end_frame = int(end_time * fps)
    stems_data = per_frame.get("stems", {})

    for stem_name, stem_data in stems_data.items():
        energy = stem_data.get("energy", [])
        if energy:
            seg_energy = energy[start_frame:end_frame]
            avg = float(np.mean(seg_energy)) if seg_energy else 0.0
        else:
            avg = 0.0

        if stem_name == "drums":
            profile.drums_energy = avg
        elif stem_name == "bass":
            profile.bass_energy = avg
        elif stem_name == "other":
            profile.synth_energy = avg
        elif stem_name == "vocals":
            profile.vocals_energy = avg

    # Determine dominant stem
    energies = {
        "drums": profile.drums_energy,
        "bass": profile.bass_energy,
        "synths": profile.synth_energy,
        "vocals": profile.vocals_energy,
    }
    profile.dominant_stem = max(energies, key=energies.get)

    # Detect key sonic characteristics
    for event in segment_events:
        stem = event.get("stem", "")
        etype = event.get("event_type", "")
        character = event.get("spectral_character", "")

        if stem == "vocals" and etype in ("onset", "sustained"):
            profile.has_vocal = True
        if stem == "other" and etype == "stab":
            profile.has_synth_stab = True
        if stem == "other" and character == "gritty":
            profile.synth_character = "gritty"
        elif stem == "other" and character == "bright" and profile.synth_character == "clean":
            profile.synth_character = "bright"
        if stem == "bass" and etype == "drop":
            profile.has_bass_drop = True
        if stem == "drums" and etype in ("buildup", "drop"):
            profile.has_drum_break = True
        if stem == "other" and etype == "buildup":
            profile.has_riser = True
        if etype == "silence":
            profile.has_silence_moment = True

    # Build the sonic prompt — what's happening musically
    prompt_parts = []
    eye_parts = []

    # Describe the dominant energy
    total_energy = sum(energies.values())
    if total_energy > 2.5:
        prompt_parts.append("maximum sonic intensity, all elements hitting hard")
    elif total_energy > 1.5:
        prompt_parts.append("high energy, multiple elements active")
    elif total_energy > 0.8:
        prompt_parts.append("moderate energy, building presence")
    else:
        prompt_parts.append("sparse, minimal elements, breathing space")

    # Describe specific sonic events
    if profile.has_bass_drop:
        prompt_parts.append("MASSIVE bass drop shaking the ground")
        eye_parts.append(EYE_REACTIONS.get("bass_drop", ""))

    if profile.has_synth_stab:
        stab_desc = STEM_VISUAL_LANGUAGE["other"].get("stab", "synth burst")
        if profile.synth_character == "gritty":
            stab_desc = "dirty gritty synth stab cutting through, distorted electronic growl"
            eye_parts.append(EYE_REACTIONS.get("other_gritty", ""))
        elif profile.synth_character == "bright":
            stab_desc = "bright shimmering synth stab, crystalline electronic burst"
            eye_parts.append(EYE_REACTIONS.get("other_bright", ""))
        prompt_parts.append(stab_desc)

    if profile.has_riser:
        prompt_parts.append("rising synth energy building tension, accelerating toward climax")
        eye_parts.append(EYE_REACTIONS.get("other_buildup", ""))

    if profile.has_drum_break:
        prompt_parts.append("intense drum pattern, percussive energy driving forward")
        eye_parts.append(EYE_REACTIONS.get("drums_drop", ""))

    if profile.has_vocal:
        prompt_parts.append("vocal element present, organic human energy in the mix")
        eye_parts.append(EYE_REACTIONS.get("vocals_onset", ""))

    if profile.has_silence_moment:
        prompt_parts.append("moment of silence creating tension, brief void before impact")
        eye_parts.append(EYE_REACTIONS.get("drums_silence", ""))

    # Describe the dominant stem character
    if profile.drums_energy > 0.6:
        prompt_parts.append("heavy percussive drive, drums dominating")
    if profile.bass_energy > 0.6:
        prompt_parts.append("deep bass weight, sub frequencies prominent")
        eye_parts.append(EYE_REACTIONS.get("bass_sustained", ""))
    if profile.synth_energy > 0.5:
        char = profile.synth_character
        synth_desc = STEM_VISUAL_LANGUAGE["other"].get(char, "electronic texture")
        prompt_parts.append(f"synth presence: {synth_desc}")

    profile.sonic_prompt = ", ".join(p for p in prompt_parts if p)
    profile.eye_prompt = ", ".join(p for p in eye_parts if p)

    # Build events summary for logging
    event_types = {}
    for e in segment_events:
        key = f"{e['stem']}_{e['event_type']}"
        event_types[key] = event_types.get(key, 0) + 1
    top_events = sorted(event_types.items(), key=lambda x: -x[1])[:5]
    profile.events_summary = "; ".join(f"{k}:{v}" for k, v in top_events)

    return profile


def enhance_segment_prompt(
    base_prompt: str,
    sonic_profile: SegmentSonicProfile,
    include_eyes: bool = True,
) -> str:
    """
    Enhance a video generation prompt with sonic event information.

    Combines the base prompt (from brand guide section) with
    sonic-reactive modifiers from the stem analysis.
    """
    parts = [base_prompt]

    if sonic_profile.sonic_prompt:
        parts.append(f"Music energy: {sonic_profile.sonic_prompt}")

    if include_eyes and sonic_profile.eye_prompt:
        parts.append(f"Eye reactions: {sonic_profile.eye_prompt}")

    return ", ".join(parts)


def create_segment_sonic_profiles(
    timeline: dict,
    segments: list[dict],
    brand_config: Optional[dict] = None,
) -> list[SegmentSonicProfile]:
    """
    Create sonic profiles for all planned video segments.

    Args:
        timeline: Full event timeline
        segments: List of segment dicts with start/end times
        brand_config: Optional brand guide

    Returns:
        List of SegmentSonicProfile, one per segment
    """
    profiles = []
    for seg in segments:
        start = seg.get("start", seg.get("start_time", 0))
        end = seg.get("end", seg.get("end_time", start + 10))
        profile = analyze_segment_sonics(timeline, start, end, brand_config)
        profiles.append(profile)
        logger.debug(
            f"Segment {start:.1f}-{end:.1f}s: "
            f"drums={profile.drums_energy:.2f} bass={profile.bass_energy:.2f} "
            f"synth={profile.synth_energy:.2f} vocals={profile.vocals_energy:.2f} "
            f"events={profile.event_count} dominant={profile.dominant_stem}"
        )
    return profiles
