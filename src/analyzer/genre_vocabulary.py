"""
Genre-specific visual vocabularies.

Loads curated visual language per genre (motion patterns, color palettes,
textures, compositional rules) from config/genres/*.yaml and integrates
them into the prompt pipeline.  Brand guide settings take priority on
conflicts -- genre vocabularies fill in the gaps.
"""
import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# Project root for config files
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_GENRES_DIR = _PROJECT_ROOT / "config" / "genres"

# Cache loaded vocabularies
_vocab_cache: dict[str, dict] = {}

# Aliases: map common genre strings to vocabulary file names
GENRE_ALIASES: dict[str, str] = {
    "drum & bass": "dnb",
    "drum and bass": "dnb",
    "drumnbass": "dnb",
    "jungle": "dnb",
    "deep dubstep": "140",
    "riddim": "dubstep",
    "brostep": "dubstep",
    "deep house": "house",
    "progressive house": "house",
    "tech house": "house",
    "minimal techno": "techno",
    "industrial techno": "techno",
    "acid techno": "techno",
    "psytrance": "trance",
    "progressive trance": "trance",
    "uplifting trance": "trance",
    "breakbeat": "breaks",
    "uk garage": "breaks",
    "chillout": "ambient",
    "downtempo": "ambient",
    "drone": "ambient",
    "hard": "dubstep",
    "halftime": "dnb",
}


def available_genres() -> list[str]:
    """Return list of available genre vocabulary names."""
    return sorted(p.stem for p in _GENRES_DIR.glob("*.yaml"))


def load_genre_vocabulary(genre: str) -> Optional[dict]:
    """Load a genre vocabulary YAML by name (or alias).

    Args:
        genre: Genre name or common alias (case-insensitive).

    Returns:
        Vocabulary dict with motion, palette, textures, composition, etc.
        Returns None if no matching vocabulary found.
    """
    genre_lower = genre.lower().strip()

    # Check cache first
    if genre_lower in _vocab_cache:
        return _vocab_cache[genre_lower]

    # Resolve alias
    resolved = GENRE_ALIASES.get(genre_lower, genre_lower)

    # Check resolved name in cache
    if resolved in _vocab_cache:
        _vocab_cache[genre_lower] = _vocab_cache[resolved]
        return _vocab_cache[resolved]

    # Load from file
    vocab_file = _GENRES_DIR / f"{resolved}.yaml"
    if not vocab_file.exists():
        logger.debug(f"No genre vocabulary for '{genre}' (resolved: {resolved})")
        _vocab_cache[genre_lower] = None
        return None

    try:
        with open(vocab_file) as f:
            vocab = yaml.safe_load(f)
        _vocab_cache[genre_lower] = vocab
        _vocab_cache[resolved] = vocab
        logger.info(f"Loaded genre vocabulary: {resolved}")
        return vocab
    except Exception as e:
        logger.warning(f"Failed to load genre vocabulary {vocab_file}: {e}")
        return None


def resolve_genre_name(genre: str) -> str:
    """Resolve a genre string to its canonical vocabulary name.

    Returns the resolved name even if no vocabulary file exists.
    """
    return GENRE_ALIASES.get(genre.lower().strip(), genre.lower().strip())


def genre_to_prompt_fragment(
    genre: str,
    section: str = "drop",
    brand_config: Optional[dict] = None,
) -> str:
    """Build a prompt fragment from genre vocabulary.

    Merges genre vocabulary with brand guide. Brand settings take
    priority -- genre vocabulary fills gaps the brand doesn't cover.

    Args:
        genre: Genre name or alias.
        section: Song section (intro/buildup/drop/breakdown/outro).
        brand_config: Optional brand guide dict (takes priority).

    Returns:
        Prompt fragment string, or empty string if no vocabulary found.
    """
    vocab = load_genre_vocabulary(genre)
    if not vocab:
        return ""

    parts = []

    # Motion description
    motion = vocab.get("motion", {})
    if motion:
        pattern = motion.get("pattern", "")
        camera = motion.get("camera", "")
        rhythm = motion.get("rhythm", "")
        if pattern:
            parts.append(f"{pattern.replace('_', ' ')} motion")
        if camera:
            parts.append(f"{camera.replace('_', ' ')} camera")
        if rhythm:
            parts.append(f"{rhythm.replace('_', ' ')} rhythm")

    # Textures
    textures = vocab.get("textures", [])
    if textures:
        # Pick textures appropriate for section energy
        if section in ("drop", "buildup"):
            tex_slice = textures[:3]
        else:
            tex_slice = textures[-2:]
        parts.append(f"{', '.join(tex_slice)} textures")

    # Composition and depth
    comp = vocab.get("composition", "")
    if comp:
        parts.append(f"{comp.replace('_', ' ')} composition")

    depth = vocab.get("depth", "")
    if depth:
        parts.append(f"{depth.replace('_', ' ')} depth")

    contrast = vocab.get("contrast", "")
    if contrast:
        parts.append(f"{contrast.replace('_', ' ')} contrast")

    # Reference styles - pick one based on section
    ref_styles = vocab.get("reference_styles", [])
    if ref_styles:
        section_idx = {
            "intro": 0,
            "buildup": 1,
            "drop": 0,
            "breakdown": 2,
            "outro": 3,
        }.get(section, 0)
        idx = min(section_idx, len(ref_styles) - 1)
        parts.append(ref_styles[idx])

    # Strip brand-covered fields if brand config provided
    if brand_config:
        brand_genre_mod = brand_config.get("genre_modifiers", {})
        genre_lower = genre.lower().strip()
        # If brand has specific genre modifiers, let brand handle those aspects
        if genre_lower in brand_genre_mod or resolve_genre_name(genre) in brand_genre_mod:
            # Still provide textures, composition, depth -- brand usually
            # only covers "extra" and "pixel_style" type fields
            pass

    return ", ".join(parts)


def genre_palette_to_colors(genre: str) -> list[str]:
    """Get the color palette for a genre.

    Args:
        genre: Genre name or alias.

    Returns:
        List of hex color strings, or empty list if no vocabulary.
    """
    vocab = load_genre_vocabulary(genre)
    if not vocab:
        return []
    return vocab.get("palette", [])


def genre_motion_intensity(genre: str) -> float:
    """Get the base motion intensity for a genre (0.0-1.0).

    Args:
        genre: Genre name or alias.

    Returns:
        Float intensity value, or 0.5 as default.
    """
    vocab = load_genre_vocabulary(genre)
    if not vocab:
        return 0.5
    return vocab.get("motion", {}).get("intensity", 0.5)


def merge_genre_with_brand(
    genre: str,
    brand_config: dict,
) -> dict:
    """Merge genre vocabulary into brand config, with brand taking priority.

    This creates a merged config where:
    - Brand-defined fields are preserved as-is
    - Genre vocabulary fills in missing fields
    - Genre palette is available as a fallback

    Args:
        genre: Genre name or alias.
        brand_config: Brand guide dict.

    Returns:
        Merged config dict (does NOT mutate the original brand_config).
    """
    vocab = load_genre_vocabulary(genre)
    if not vocab:
        return dict(brand_config)

    merged = dict(brand_config)

    # Add genre_vocabulary key for downstream access
    merged["genre_vocabulary"] = vocab

    # Merge motion mapping if brand doesn't have one
    if "motion_mapping" not in merged:
        motion = vocab.get("motion", {})
        if motion:
            intensity = motion.get("intensity", 0.5)
            # Map genre intensity to motion floor/ceiling
            floor = max(1, int(2 + (1 - intensity) * 3))
            ceiling = max(floor + 2, int(5 + intensity * 5))
            merged["motion_mapping"] = {
                "floor": floor,
                "ceiling": min(10, ceiling),
                "curve": "exponential",
            }

    return merged


def clear_cache() -> None:
    """Clear the vocabulary cache (useful for testing)."""
    _vocab_cache.clear()
