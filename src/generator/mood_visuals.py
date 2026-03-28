"""
Mood-to-visual parameter mapping.

Translates mood analysis (valence, arousal, mood probabilities) into
concrete visual parameters that affect:
- AI image generation prompts (mood descriptors, color guidance)
- Beat-sync effect intensity (flash, zoom, strobe)
- Color grading (temperature, saturation, contrast)
- Motion characteristics (speed, blur, Ken Burns intensity)

Uses Russell's circumplex model:
  Euphoric (high valence + high arousal) → warm, vibrant, fast, dynamic
  Tense (low valence + high arousal) → cool/red, high contrast, aggressive
  Melancholic (low valence + low arousal) → desaturated, slow, dark
  Serene (high valence + low arousal) → soft, warm, gentle, minimal
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MoodVisualParams:
    """Visual parameters derived from mood analysis."""

    # Prompt modifiers (added to AI image generation prompts)
    prompt_mood_prefix: str = ""  # e.g., "euphoric and vibrant"
    prompt_color_guide: str = ""  # e.g., "warm golden hues, bright saturated colors"
    prompt_atmosphere: str = ""  # e.g., "explosive energy, triumphant"

    # Color grading
    color_temperature: float = 0.5  # 0=cool/blue, 1=warm/orange
    saturation_mult: float = 1.0  # Multiply base saturation
    contrast_mult: float = 1.0  # Multiply base contrast
    brightness_offset: float = 0.0  # Add to base brightness

    # Beat-sync effects
    flash_intensity_mult: float = 1.0  # Multiply beat flash
    zoom_intensity_mult: float = 1.0  # Multiply zoom pulse
    strobe_recommend: bool = False  # Suggest strobe for this mood
    motion_speed: float = 1.0  # Multiplier for animation speed

    # Ken Burns
    ken_burns_intensity: float = 1.0  # Multiplier for pan/zoom range

    # Style recommendations
    recommended_styles: list[str] = None  # Top style picks for this mood

    def __post_init__(self):
        if self.recommended_styles is None:
            self.recommended_styles = []


def map_mood_to_visuals(mood_data: dict) -> MoodVisualParams:
    """
    Map mood analysis data to visual parameters.

    Args:
        mood_data: Dict with keys: valence, arousal, happy, sad, aggressive,
                   relaxed, party, quadrant, mood_descriptor

    Returns:
        MoodVisualParams with all visual parameters set
    """
    valence = mood_data.get("valence", 0.5)
    arousal = mood_data.get("arousal", 0.5)
    quadrant = mood_data.get("quadrant", "euphoric")

    happy = mood_data.get("happy", 0.5)
    sad = mood_data.get("sad", 0.1)
    aggressive = mood_data.get("aggressive", 0.3)
    relaxed = mood_data.get("relaxed", 0.3)
    party = mood_data.get("party", 0.3)

    params = MoodVisualParams()

    # ── Prompt modifiers ──

    if quadrant == "euphoric":
        params.prompt_mood_prefix = "euphoric, uplifting, triumphant, joyful"
        if party > 0.7:
            params.prompt_color_guide = "vibrant neon colors, electric pink, bright cyan, golden highlights, festival lighting"
            params.prompt_atmosphere = "explosive celebration, peak festival moment, crowd euphoria"
        elif happy > 0.8:
            params.prompt_color_guide = "warm golden light, bright saturated colors, sunburst orange, radiant white"
            params.prompt_atmosphere = "triumphant ascent, breakthrough moment, pure joy"
        else:
            params.prompt_color_guide = "bright energetic colors, vibrant blue and orange, dynamic contrast"
            params.prompt_atmosphere = "high energy, forward momentum, exciting"

    elif quadrant == "tense":
        params.prompt_mood_prefix = "dark, aggressive, intense, menacing"
        if aggressive > 0.7:
            params.prompt_color_guide = "deep crimson red, dark black, blood orange, industrial metal tones"
            params.prompt_atmosphere = "raw power, destructive force, relentless intensity, industrial warfare"
        else:
            params.prompt_color_guide = "dark purple, deep blue, electric red accents, high contrast shadows"
            params.prompt_atmosphere = "building tension, ominous, driving force, underground"

    elif quadrant == "melancholic":
        params.prompt_mood_prefix = "melancholic, introspective, haunting, ethereal"
        if sad > 0.6:
            params.prompt_color_guide = "muted blues, grey tones, faded violet, desaturated, cold mist"
            params.prompt_atmosphere = "deep sorrow, lonely emptiness, fading memories, rain"
        else:
            params.prompt_color_guide = "dark teal, deep indigo, subtle purple, low contrast"
            params.prompt_atmosphere = "brooding atmosphere, contemplative darkness, slow decay"

    elif quadrant == "serene":
        params.prompt_mood_prefix = "peaceful, dreamy, ethereal, floating"
        if relaxed > 0.7:
            params.prompt_color_guide = "soft pastels, gentle lavender, warm amber glow, diffused light"
            params.prompt_atmosphere = "tranquil meditation, gentle floating, cosmic peace"
        else:
            params.prompt_color_guide = "soft warm tones, gentle gradients, subtle golden hour light"
            params.prompt_atmosphere = "calm waters, gentle breeze, natural beauty, stillness"

    # ── Color grading ──

    # Temperature: valence drives warm/cool (happy=warm, sad=cool)
    params.color_temperature = 0.3 + valence * 0.4  # 0.3 (cool) to 0.7 (warm)
    if aggressive > 0.7:
        params.color_temperature = min(params.color_temperature + 0.15, 0.85)  # Aggressive = warmer (reds)

    # Saturation: arousal drives saturation (energetic=vivid, calm=muted)
    params.saturation_mult = 0.6 + arousal * 0.8  # 0.6 (muted) to 1.4 (vivid)
    if sad > 0.5:
        params.saturation_mult *= 0.7  # Sad = desaturated

    # Contrast: arousal + aggressive drive contrast
    params.contrast_mult = 0.8 + arousal * 0.3 + aggressive * 0.2  # 0.8 to 1.3
    if relaxed > 0.6:
        params.contrast_mult *= 0.85  # Relaxed = lower contrast

    # Brightness: valence drives brightness
    params.brightness_offset = (valence - 0.5) * 0.15  # -0.075 to +0.075

    # ── Beat-sync effects ──

    # Flash intensity: arousal-driven
    params.flash_intensity_mult = 0.5 + arousal * 1.0  # 0.5 to 1.5
    if relaxed > 0.6:
        params.flash_intensity_mult *= 0.5  # Minimal flash for relaxed tracks

    # Zoom intensity: arousal + party
    params.zoom_intensity_mult = 0.5 + arousal * 0.8 + party * 0.3  # 0.5 to 1.6

    # Strobe recommendation: only for high-energy aggressive/party tracks
    params.strobe_recommend = (arousal > 0.7 and (aggressive > 0.5 or party > 0.7))

    # Motion speed: arousal-driven
    params.motion_speed = 0.6 + arousal * 0.8  # 0.6 to 1.4

    # Ken Burns intensity: inverse of arousal (calm = more subtle motion)
    params.ken_burns_intensity = 0.5 + (1.0 - arousal) * 0.8  # 0.5 (fast) to 1.3 (calm=more KB)

    # ── Style recommendations ──

    if quadrant == "euphoric":
        if party > 0.7:
            params.recommended_styles = ["laser", "cyberpunk", "abstract"]
        else:
            params.recommended_styles = ["abstract", "nature", "cosmic"]
    elif quadrant == "tense":
        if aggressive > 0.7:
            params.recommended_styles = ["fire", "glitch", "laser"]
        else:
            params.recommended_styles = ["cyberpunk", "glitch", "minimal"]
    elif quadrant == "melancholic":
        params.recommended_styles = ["cosmic", "nature", "liquid"]
    elif quadrant == "serene":
        params.recommended_styles = ["nature", "liquid", "cosmic"]

    return params


def enhance_prompt_with_mood(base_prompt: str, mood_params: MoodVisualParams) -> str:
    """
    Enhance an AI image generation prompt with mood-derived modifiers.
    Prepends mood atmosphere and color guidance to the base style prompt.
    """
    parts = []

    if mood_params.prompt_mood_prefix:
        parts.append(mood_params.prompt_mood_prefix)

    parts.append(base_prompt)

    if mood_params.prompt_color_guide:
        parts.append(mood_params.prompt_color_guide)

    if mood_params.prompt_atmosphere:
        parts.append(mood_params.prompt_atmosphere)

    return ", ".join(parts)
