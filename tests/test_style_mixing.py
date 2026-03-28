"""Tests for style mixing per phrase type."""
from src.generator.engine import resolve_phrase_style, GenerationConfig


def test_resolve_phrase_style_no_overrides():
    """With no overrides, always returns default style."""
    default = {"name": "abstract", "prompts": {"drop": "abstract drop"}}
    assert resolve_phrase_style("drop", None, default) is default
    assert resolve_phrase_style("buildup", None, default) is default
    assert resolve_phrase_style("intro", None, default) is default


def test_resolve_phrase_style_empty_overrides():
    """Empty overrides dict returns default."""
    default = {"name": "abstract"}
    assert resolve_phrase_style("drop", {}, default) is default


def test_resolve_phrase_style_direct_match():
    """Direct label match returns the override style."""
    default = {"name": "abstract"}
    fire_style = {"name": "fire", "prompts": {"drop": "fire drop"}}
    overrides = {"drop": fire_style}

    result = resolve_phrase_style("drop", overrides, default)
    assert result is fire_style
    # Non-overridden label falls back to default
    assert resolve_phrase_style("buildup", overrides, default) is default


def test_resolve_phrase_style_outro_falls_back_to_intro():
    """Outro uses intro override when no explicit outro override exists."""
    default = {"name": "abstract"}
    intro_style = {"name": "nature"}
    overrides = {"intro": intro_style}

    result = resolve_phrase_style("outro", overrides, default)
    assert result is intro_style


def test_resolve_phrase_style_explicit_outro():
    """Explicit outro override takes priority over intro fallback."""
    default = {"name": "abstract"}
    intro_style = {"name": "nature"}
    outro_style = {"name": "cosmic"}
    overrides = {"intro": intro_style, "outro": outro_style}

    assert resolve_phrase_style("outro", overrides, default) is outro_style
    assert resolve_phrase_style("intro", overrides, default) is intro_style


def test_resolve_phrase_style_all_types():
    """All phrase types can be overridden independently."""
    default = {"name": "abstract"}
    overrides = {
        "drop": {"name": "fire"},
        "buildup": {"name": "laser"},
        "breakdown": {"name": "liquid"},
        "intro": {"name": "nature"},
    }

    assert resolve_phrase_style("drop", overrides, default)["name"] == "fire"
    assert resolve_phrase_style("buildup", overrides, default)["name"] == "laser"
    assert resolve_phrase_style("breakdown", overrides, default)["name"] == "liquid"
    assert resolve_phrase_style("intro", overrides, default)["name"] == "nature"
    assert resolve_phrase_style("outro", overrides, default)["name"] == "nature"  # falls back


def test_generation_config_style_overrides_default_none():
    """GenerationConfig.style_overrides defaults to None."""
    config = GenerationConfig()
    assert config.style_overrides is None


def test_generation_config_accepts_style_overrides():
    """GenerationConfig can be constructed with style_overrides."""
    overrides = {"drop": {"name": "fire"}}
    config = GenerationConfig(style_overrides=overrides)
    assert config.style_overrides == overrides
