"""
Professional VJ prompt engineering for AI video generation.

Builds high-quality prompts that produce festival-grade visuals.
Each prompt is crafted based on:
- Song section (intro/buildup/drop/breakdown/outro)
- Mood analysis (valence, arousal, quadrant)
- Genre characteristics
- Visual style preference
- Motion guidance (smooth vs energetic)
- Professional VJ content principles (volumetric lighting, depth, fluid motion)

The prompts reference techniques from top VJ creators:
- Volumetric 3D environments (tunnels, rooms, infinite spaces)
- High-contrast neon on black (optimized for LED walls)
- Organic fluid simulations (liquid metal, smoke, ink-in-water)
- Geometric abstractions with rhythmic motion
- Cinematic lighting (rim lights, god rays, atmospheric haze)
"""
import logging
from typing import Optional

from ..analyzer.genre_vocabulary import genre_to_prompt_fragment, load_genre_vocabulary

logger = logging.getLogger(__name__)

# Base quality markers that go on every prompt
QUALITY_SUFFIX = (
    "masterful cinematography, professional VJ content, "
    "volumetric lighting, atmospheric depth, "
    "smooth continuous motion, 4K quality, "
    "no text, no watermarks, no people, no faces"
)

# Motion guidance per section type
MOTION_GUIDE = {
    "intro": "very slow subtle camera drift, gentle reveal, establishing atmosphere",
    "buildup": "gradually accelerating camera movement, increasing visual complexity, building tension",
    "drop": "explosive dynamic camera motion, rapid energy, powerful visual impact, maximum intensity",
    "breakdown": "slow floating camera, dreamy gentle drift, contemplative atmosphere",
    "outro": "gradually decelerating, fading energy, peaceful resolution",
}

# Energy-to-visual mapping
ENERGY_MODIFIERS = {
    "very_low": "minimal, sparse, vast empty space, single focal point",
    "low": "gentle, soft, ambient glow, subtle movement",
    "medium": "moderate energy, balanced composition, rhythmic flow",
    "high": "vibrant, dynamic, complex layered motion, intense colors",
    "very_high": "maximum intensity, overwhelming visual power, explosive energy, peak moment",
}

# Mood quadrant visual characteristics
MOOD_VISUALS = {
    "euphoric": {
        "colors": "vibrant warm neon colors, electric pink, bright cyan, golden highlights, rainbow prismatic light",
        "atmosphere": "triumphant ascending energy, festival peak moment, pure joy and celebration",
        "lighting": "brilliant radiant light, lens flares, volumetric god rays, glowing particles",
        "texture": "crystalline, iridescent, liquid gold, prismatic glass",
    },
    "tense": {
        "colors": "deep crimson red, dark obsidian black, blood orange accents, industrial metal tones",
        "atmosphere": "raw aggressive power, dark underground intensity, mechanical warfare",
        "lighting": "harsh directional light, deep shadows, red warning glow, strobing",
        "texture": "rough metal, cracked concrete, molten lava, dark smoke",
    },
    "melancholic": {
        "colors": "muted desaturated blues, cold grey tones, faded violet, monochrome with subtle teal",
        "atmosphere": "lonely vast emptiness, rain on glass, distant memories fading",
        "lighting": "dim diffused light, cold blue ambient, gentle fog, overcast",
        "texture": "weathered stone, frosted glass, still water, dust particles",
    },
    "serene": {
        "colors": "soft warm pastels, gentle lavender, amber sunset glow, pearl white",
        "atmosphere": "peaceful floating meditation, cosmic tranquility, gentle nature",
        "lighting": "soft golden hour light, diffused warmth, gentle rim lighting",
        "texture": "silk, soft clouds, calm water reflections, flower petals",
    },
}

# Genre-specific visual vocabularies
GENRE_VISUALS = {
    "drum & bass": "dark tunnel environments, industrial architecture, fast-moving geometric shards, metallic surfaces, bass-heavy visual weight",
    "dnb": "dark tunnel environments, industrial architecture, fast-moving geometric shards, metallic surfaces, bass-heavy visual weight",
    "dubstep": "heavy mechanical structures, dark industrial, bass-reactive geometry, glitch distortion, massive scale",
    "house": "flowing organic forms, warm colors, smooth gradients, sunset atmospheres, elegant minimalism",
    "techno": "precise geometric patterns, monochrome palette, industrial repetition, hypnotic symmetry, minimal architecture",
    "trance": "cosmic nebula environments, ethereal light trails, vast celestial spaces, spiritual ascending energy, aurora effects",
    "ambient": "vast natural landscapes, gentle atmospheric phenomena, soft particle systems, peaceful environments",
    "140": "dark industrial spaces, aggressive geometry, bass-heavy visual elements, dystopian environments",
}

# Visual style presets (can be selected by user)
STYLE_PRESETS = {
    "tunnel": "infinite 3D tunnel with glowing neon edges, camera flying through at speed, geometric wireframe structure",
    "particles": "millions of glowing particles in 3D space, flowing like a fluid, forming and dissolving shapes",
    "fluid": "mesmerizing fluid dynamics simulation, metallic liquid with iridescent surface, macro lens perspective",
    "geometric": "precise mathematical geometry, rotating polyhedra, fractal structures, perfect symmetry",
    "organic": "bioluminescent organic forms, pulsating tendrils, alien plant life, deep sea creatures",
    "space": "deep space nebula, cosmic dust clouds, star formation, planetary atmospheres, Hubble-quality",
    "abstract": "non-representational flowing forms, color field painting in motion, pure visual rhythm",
    "neon": "high contrast neon elements on pure black, light painting, laser beam patterns, glow effects",
    "nature": "surreal hyperreal nature, bioluminescent forests, aurora skies, crystal caves",
    "industrial": "abandoned industrial cathedral, rust and metal, sparks, mechanical motion, brutalist architecture",
}


def build_video_prompt(
    section_label: str,
    mood_data: Optional[dict] = None,
    genre: str = "",
    style: str = "abstract",
    energy_level: float = 0.5,
    custom_prompt: str = "",
) -> str:
    """
    Build a professional VJ video generation prompt.

    Args:
        section_label: intro, buildup, drop, breakdown, outro
        mood_data: Dict with valence, arousal, quadrant, mood_descriptor
        genre: Music genre (from Lexicon or auto-detected)
        style: Visual style preset name
        energy_level: 0.0-1.0 energy of this section
        custom_prompt: Optional user override

    Returns:
        A carefully crafted prompt for AI video generation
    """
    if custom_prompt:
        return f"{custom_prompt}, {QUALITY_SUFFIX}"

    parts = []

    # Style preset
    style_lower = style.lower()
    if style_lower in STYLE_PRESETS:
        parts.append(STYLE_PRESETS[style_lower])
    else:
        parts.append(f"{style} visual style")

    # Mood-based visuals
    if mood_data:
        quadrant = mood_data.get("quadrant", "euphoric")
        mood_vis = MOOD_VISUALS.get(quadrant, MOOD_VISUALS["euphoric"])
        parts.append(mood_vis["colors"])
        parts.append(mood_vis["atmosphere"])
        parts.append(mood_vis["lighting"])
    else:
        parts.append("vibrant colors, cinematic lighting, atmospheric depth")

    # Genre-specific vocabulary (structured YAML first, fallback to inline dict)
    genre_lower = genre.lower() if genre else ""
    genre_fragment = genre_to_prompt_fragment(genre, section_label) if genre else ""
    if genre_fragment:
        parts.append(genre_fragment)
    else:
        for genre_key, genre_vis in GENRE_VISUALS.items():
            if genre_key in genre_lower:
                parts.append(genre_vis)
                break

    # Section-specific motion guidance
    motion = MOTION_GUIDE.get(section_label, MOTION_GUIDE["drop"])
    parts.append(motion)

    # Energy modifier
    if energy_level >= 0.8:
        parts.append(ENERGY_MODIFIERS["very_high"])
    elif energy_level >= 0.6:
        parts.append(ENERGY_MODIFIERS["high"])
    elif energy_level >= 0.4:
        parts.append(ENERGY_MODIFIERS["medium"])
    elif energy_level >= 0.2:
        parts.append(ENERGY_MODIFIERS["low"])
    else:
        parts.append(ENERGY_MODIFIERS["very_low"])

    # Quality suffix
    parts.append(QUALITY_SUFFIX)

    prompt = ", ".join(parts)

    # Truncate if too long (most models have ~500 char limit)
    if len(prompt) > 800:
        prompt = prompt[:800]

    logger.debug(f"Prompt [{section_label}]: {prompt[:100]}...")
    return prompt


def build_keyframe_prompt(
    section_label: str,
    mood_data: Optional[dict] = None,
    genre: str = "",
    style: str = "abstract",
    energy_level: float = 0.5,
) -> str:
    """
    Build a prompt for keyframe image generation (DALL-E 3 / Flux).
    Keyframes are then animated by the video model.

    Keyframe prompts are more detailed about composition since
    they define the starting visual that the video model animates from.
    """
    video_prompt = build_video_prompt(
        section_label, mood_data, genre, style, energy_level
    )

    # Add keyframe-specific guidance
    keyframe_extras = (
        "single perfectly composed frame, "
        "dramatic composition, rule of thirds, "
        "high detail, sharp focus, "
        "suitable as first frame of a smooth video"
    )

    return f"{keyframe_extras}, {video_prompt}"
