"""
Seasonal and venue-specific theme layers.

Applies theme overlays on top of the brand guide, modifying color
grading, prompt prefixes/suffixes, and venue-specific adjustments.

Two application modes:
1. Post-process: color grading metadata for ffmpeg filters (no regeneration)
2. Regenerate: inject theme into prompts for fresh generation

Theme scheduling: auto-selects theme based on current date.
"""
import logging
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_THEMES_DIR = _PROJECT_ROOT / "config" / "themes"

# Cache loaded themes
_theme_cache: dict[str, dict] = {}


def available_themes() -> list[str]:
    """List all available theme names."""
    return sorted(p.stem for p in _THEMES_DIR.glob("*.yaml"))


def load_theme(name: str) -> Optional[dict]:
    """Load a theme YAML config by name.

    Args:
        name: Theme name (filename without .yaml).

    Returns:
        Theme dict, or None if not found.
    """
    if name in _theme_cache:
        return _theme_cache[name]

    theme_file = _THEMES_DIR / f"{name}.yaml"
    if not theme_file.exists():
        logger.debug(f"Theme not found: {name}")
        return None

    try:
        with open(theme_file) as f:
            theme = yaml.safe_load(f)
        _theme_cache[name] = theme
        return theme
    except Exception as e:
        logger.warning(f"Failed to load theme {name}: {e}")
        return None


def get_scheduled_theme(today: Optional[date] = None) -> Optional[str]:
    """Get the theme that should be active based on today's date.

    Checks all themes with 'schedule' config and returns the first
    matching theme.

    Args:
        today: Override date for testing (defaults to today).

    Returns:
        Theme name, or None if no scheduled theme matches.
    """
    if today is None:
        today = date.today()

    for name in available_themes():
        theme = load_theme(name)
        if not theme:
            continue

        schedule = theme.get("schedule")
        if not schedule:
            continue

        start_month = schedule.get("start_month", 1)
        start_day = schedule.get("start_day", 1)
        end_month = schedule.get("end_month", 12)
        end_day = schedule.get("end_day", 31)

        try:
            # Handle year-wrapping schedules (e.g., Dec 28 -> Jan 2)
            if start_month > end_month:
                # Wraps around year
                start_date = date(today.year, start_month, start_day)
                end_date = date(today.year + 1, end_month, end_day)
                # Check if today falls in the range
                if today >= start_date or today <= date(today.year, end_month, end_day):
                    return name
            else:
                start_date = date(today.year, start_month, start_day)
                end_date = date(today.year, end_month, end_day)
                if start_date <= today <= end_date:
                    return name
        except ValueError:
            continue

    return None


def apply_theme_to_prompt(
    prompt: str,
    theme_name: str,
) -> str:
    """Apply a theme's prompt modifications to a generation prompt.

    Adds prefix and suffix from the theme config.

    Args:
        prompt: Original generation prompt.
        theme_name: Theme to apply.

    Returns:
        Modified prompt with theme prefix and suffix.
    """
    theme = load_theme(theme_name)
    if not theme:
        return prompt

    parts = []

    prefix = theme.get("prompt_prefix", "")
    if prefix:
        parts.append(prefix)

    parts.append(prompt)

    suffix = theme.get("prompt_suffix", "")
    if suffix:
        parts.append(suffix)

    return ", ".join(parts)


def get_color_grading_params(theme_name: str) -> dict:
    """Get ffmpeg-compatible color grading parameters for post-processing.

    Returns parameters that can be used with ffmpeg's eq and hue filters.

    Args:
        theme_name: Theme to get color grading for.

    Returns:
        Dict with hue_rotate, saturation, brightness, contrast, gamma.
    """
    theme = load_theme(theme_name)
    if not theme:
        return {}

    color_shift = theme.get("color_shift", {})
    venue = theme.get("venue_adjustments", {})

    return {
        "hue_rotate": color_shift.get("hue_rotate", 0),
        "saturation": color_shift.get("saturation", 1.0),
        "brightness": color_shift.get("brightness", 1.0),
        "contrast": venue.get("contrast", 1.0),
        "gamma": venue.get("gamma", 1.0),
        "black_level": venue.get("black_level", 0.0),
    }


def build_ffmpeg_filter(theme_name: str) -> str:
    """Build an ffmpeg filter string for post-process color grading.

    Args:
        theme_name: Theme to build filter for.

    Returns:
        ffmpeg -vf filter string, or empty string if no adjustments needed.
    """
    params = get_color_grading_params(theme_name)
    if not params:
        return ""

    filters = []

    # Hue rotation and saturation
    hue_rotate = params.get("hue_rotate", 0)
    saturation = params.get("saturation", 1.0)
    if hue_rotate != 0 or saturation != 1.0:
        filters.append(f"hue=h={hue_rotate}:s={saturation}")

    # Brightness, contrast, gamma
    brightness = params.get("brightness", 1.0)
    contrast = params.get("contrast", 1.0)
    gamma = params.get("gamma", 1.0)
    if brightness != 1.0 or contrast != 1.0 or gamma != 1.0:
        eq_parts = []
        if brightness != 1.0:
            eq_parts.append(f"brightness={brightness - 1.0:.2f}")
        if contrast != 1.0:
            eq_parts.append(f"contrast={contrast:.2f}")
        if gamma != 1.0:
            eq_parts.append(f"gamma={gamma:.2f}")
        if eq_parts:
            filters.append(f"eq={':'.join(eq_parts)}")

    return ",".join(filters)


def merge_theme_with_brand(
    brand_config: dict,
    theme_name: str,
) -> dict:
    """Merge a theme overlay into a brand config for regeneration mode.

    Theme modifies prompt sections and adds color metadata.
    Brand settings take priority on conflicts.

    Args:
        brand_config: Brand guide dict.
        theme_name: Theme to apply.

    Returns:
        Merged config dict (does NOT mutate original).
    """
    theme = load_theme(theme_name)
    if not theme:
        return dict(brand_config)

    merged = dict(brand_config)
    merged["active_theme"] = theme_name
    merged["theme"] = theme

    # Inject theme prompt prefix/suffix into section prompts
    prefix = theme.get("prompt_prefix", "")
    suffix = theme.get("prompt_suffix", "")
    sections = merged.get("sections", {})

    if prefix or suffix:
        themed_sections = {}
        for section_name, section_data in sections.items():
            themed = dict(section_data)
            original_prompt = themed.get("prompt", "")
            parts = []
            if prefix:
                parts.append(prefix)
            parts.append(original_prompt)
            if suffix:
                parts.append(suffix)
            themed["prompt"] = ", ".join(p for p in parts if p)
            themed_sections[section_name] = themed
        merged["sections"] = themed_sections

    return merged


def clear_cache() -> None:
    """Clear the theme cache."""
    _theme_cache.clear()
