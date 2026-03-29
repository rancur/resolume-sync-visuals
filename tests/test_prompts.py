"""Tests for VJ prompt engineering (src/generator/prompts.py)."""
import pytest

from src.generator.prompts import (
    QUALITY_SUFFIX,
    MOTION_GUIDE,
    ENERGY_MODIFIERS,
    MOOD_VISUALS,
    GENRE_VISUALS,
    STYLE_PRESETS,
    build_video_prompt,
    build_keyframe_prompt,
)


class TestBuildVideoPrompt:
    def test_includes_quality_suffix(self):
        prompt = build_video_prompt("drop")
        assert "no text" in prompt
        assert "4K quality" in prompt

    def test_custom_prompt_overrides(self):
        prompt = build_video_prompt("drop", custom_prompt="my custom visual")
        assert "my custom visual" in prompt
        assert QUALITY_SUFFIX in prompt

    def test_includes_style_preset(self):
        prompt = build_video_prompt("intro", style="tunnel")
        assert "tunnel" in prompt.lower()

    def test_unknown_style_uses_literal(self):
        prompt = build_video_prompt("intro", style="my_custom_style")
        assert "my_custom_style" in prompt

    def test_includes_mood_colors(self):
        mood = {"quadrant": "euphoric", "valence": 0.8, "arousal": 0.8}
        prompt = build_video_prompt("drop", mood_data=mood)
        assert "vibrant" in prompt.lower() or "neon" in prompt.lower()

    def test_includes_genre_vocabulary(self):
        prompt = build_video_prompt("drop", genre="Drum & Bass")
        assert "tunnel" in prompt.lower() or "industrial" in prompt.lower()

    def test_includes_motion_guidance(self):
        prompt = build_video_prompt("intro")
        assert "slow" in prompt.lower() or "drift" in prompt.lower()

    def test_high_energy_modifier(self):
        prompt = build_video_prompt("drop", energy_level=0.9)
        assert "maximum intensity" in prompt.lower() or "explosive" in prompt.lower()

    def test_low_energy_modifier(self):
        prompt = build_video_prompt("intro", energy_level=0.1)
        assert "minimal" in prompt.lower() or "sparse" in prompt.lower()

    def test_truncates_long_prompts(self):
        prompt = build_video_prompt(
            "drop",
            mood_data={"quadrant": "euphoric"},
            genre="drum & bass",
            style="tunnel",
            energy_level=0.9,
        )
        assert len(prompt) <= 800


class TestBuildKeyframePrompt:
    def test_includes_composition_guidance(self):
        prompt = build_keyframe_prompt("drop")
        assert "composition" in prompt.lower() or "frame" in prompt.lower()

    def test_includes_video_prompt_content(self):
        prompt = build_keyframe_prompt("drop", style="abstract")
        # Should contain content from build_video_prompt
        assert "4K quality" in prompt

    def test_all_sections_produce_valid_prompts(self):
        for section in ["intro", "buildup", "drop", "breakdown", "outro"]:
            prompt = build_keyframe_prompt(section)
            assert len(prompt) > 50
            assert isinstance(prompt, str)


class TestConstants:
    def test_all_sections_have_motion(self):
        expected = {"intro", "buildup", "drop", "breakdown", "outro"}
        assert set(MOTION_GUIDE.keys()) == expected

    def test_all_quadrants_have_visuals(self):
        expected = {"euphoric", "tense", "melancholic", "serene"}
        assert set(MOOD_VISUALS.keys()) == expected

    def test_mood_visuals_have_all_fields(self):
        for quadrant, vis in MOOD_VISUALS.items():
            assert "colors" in vis, f"{quadrant} missing colors"
            assert "atmosphere" in vis, f"{quadrant} missing atmosphere"
            assert "lighting" in vis, f"{quadrant} missing lighting"

    def test_style_presets_not_empty(self):
        assert len(STYLE_PRESETS) >= 5
        for name, preset in STYLE_PRESETS.items():
            assert len(preset) > 10
