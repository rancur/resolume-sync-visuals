"""Tests for mood-to-visual parameter mapping (src/generator/mood_visuals.py)."""
import pytest

from src.generator.mood_visuals import (
    MoodVisualParams,
    map_mood_to_visuals,
    enhance_prompt_with_mood,
)


class TestMoodVisualParams:
    def test_defaults(self):
        p = MoodVisualParams()
        assert p.color_temperature == 0.5
        assert p.saturation_mult == 1.0
        assert p.contrast_mult == 1.0
        assert p.strobe_recommend is False
        assert p.recommended_styles == []


class TestMapMoodToVisuals:
    def test_euphoric_quadrant(self):
        mood = {"valence": 0.8, "arousal": 0.8, "quadrant": "euphoric",
                "happy": 0.9, "party": 0.5, "sad": 0.1,
                "aggressive": 0.1, "relaxed": 0.1}
        params = map_mood_to_visuals(mood)
        assert "euphoric" in params.prompt_mood_prefix
        assert params.color_temperature > 0.5
        assert params.saturation_mult > 1.0

    def test_tense_quadrant(self):
        mood = {"valence": 0.2, "arousal": 0.9, "quadrant": "tense",
                "happy": 0.1, "party": 0.1, "sad": 0.2,
                "aggressive": 0.8, "relaxed": 0.0}
        params = map_mood_to_visuals(mood)
        assert "aggressive" in params.prompt_mood_prefix or "dark" in params.prompt_mood_prefix
        assert params.contrast_mult > 1.0

    def test_melancholic_quadrant(self):
        mood = {"valence": 0.2, "arousal": 0.2, "quadrant": "melancholic",
                "happy": 0.1, "party": 0.0, "sad": 0.7,
                "aggressive": 0.1, "relaxed": 0.2}
        params = map_mood_to_visuals(mood)
        assert "melancholic" in params.prompt_mood_prefix
        assert params.saturation_mult < 1.0  # Sad = desaturated

    def test_serene_quadrant(self):
        mood = {"valence": 0.8, "arousal": 0.2, "quadrant": "serene",
                "happy": 0.5, "party": 0.1, "sad": 0.0,
                "aggressive": 0.0, "relaxed": 0.8}
        params = map_mood_to_visuals(mood)
        assert "peaceful" in params.prompt_mood_prefix or "dreamy" in params.prompt_mood_prefix
        assert params.flash_intensity_mult < 1.0  # Relaxed = minimal flash

    def test_high_party_euphoric_recommends_styles(self):
        mood = {"valence": 0.9, "arousal": 0.9, "quadrant": "euphoric",
                "happy": 0.8, "party": 0.8, "sad": 0.0,
                "aggressive": 0.1, "relaxed": 0.0}
        params = map_mood_to_visuals(mood)
        assert "laser" in params.recommended_styles

    def test_strobe_for_aggressive_high_arousal(self):
        mood = {"valence": 0.2, "arousal": 0.9, "quadrant": "tense",
                "happy": 0.0, "party": 0.2, "sad": 0.1,
                "aggressive": 0.8, "relaxed": 0.0}
        params = map_mood_to_visuals(mood)
        assert params.strobe_recommend is True

    def test_no_strobe_for_calm(self):
        mood = {"valence": 0.7, "arousal": 0.3, "quadrant": "serene",
                "happy": 0.5, "party": 0.1, "sad": 0.0,
                "aggressive": 0.0, "relaxed": 0.7}
        params = map_mood_to_visuals(mood)
        assert params.strobe_recommend is False

    def test_defaults_for_empty_mood(self):
        params = map_mood_to_visuals({})
        assert isinstance(params, MoodVisualParams)
        assert params.prompt_mood_prefix != ""


class TestEnhancePromptWithMood:
    def test_enhances_base_prompt(self):
        params = MoodVisualParams(
            prompt_mood_prefix="euphoric",
            prompt_color_guide="bright neon",
            prompt_atmosphere="festival energy",
        )
        result = enhance_prompt_with_mood("abstract flowing shapes", params)
        assert "euphoric" in result
        assert "abstract flowing shapes" in result
        assert "bright neon" in result
        assert "festival energy" in result

    def test_empty_modifiers_return_base(self):
        params = MoodVisualParams()
        result = enhance_prompt_with_mood("base prompt only", params)
        assert "base prompt only" in result
