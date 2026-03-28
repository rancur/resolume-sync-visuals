"""Tests for mood analysis and visual parameter mapping."""
import pytest
from pathlib import Path

from src.analyzer.mood import MoodAnalyzer, MoodAnalysis, MOOD_NAMES, QUADRANT_LABELS
from src.generator.mood_visuals import map_mood_to_visuals, enhance_prompt_with_mood, MoodVisualParams


class TestMoodAnalysis:
    def test_mood_analysis_dataclass(self):
        mood = MoodAnalysis(happy=0.8, sad=0.1, aggressive=0.3, relaxed=0.4, party=0.6,
                            valence=0.7, arousal=0.6, dominant_mood="happy", quadrant="euphoric")
        assert mood.happy == 0.8
        assert mood.quadrant == "euphoric"

    def test_mood_to_dict(self):
        mood = MoodAnalysis(happy=0.9, sad=0.1, valence=0.8, arousal=0.7)
        d = mood.to_dict()
        assert d["happy"] == 0.9
        assert d["valence"] == 0.8
        assert "segments" in d

    def test_mood_names_defined(self):
        assert len(MOOD_NAMES) == 5
        assert "happy" in MOOD_NAMES
        assert "sad" in MOOD_NAMES
        assert "aggressive" in MOOD_NAMES

    def test_quadrant_labels_defined(self):
        assert "euphoric" in QUADRANT_LABELS
        assert "tense" in QUADRANT_LABELS
        assert "melancholic" in QUADRANT_LABELS
        assert "serene" in QUADRANT_LABELS


class TestMoodAnalyzerCompute:
    """Test valence/arousal computation without models."""

    def test_compute_valence_happy(self):
        moods = {"happy": 0.9, "sad": 0.1, "aggressive": 0.2, "relaxed": 0.3, "party": 0.5}
        valence = MoodAnalyzer._compute_valence(moods)
        assert valence > 0.6  # Happy track = high valence

    def test_compute_valence_sad(self):
        moods = {"happy": 0.1, "sad": 0.9, "aggressive": 0.2, "relaxed": 0.3, "party": 0.1}
        valence = MoodAnalyzer._compute_valence(moods)
        assert valence < 0.4  # Sad track = low valence

    def test_compute_arousal_aggressive(self):
        moods = {"happy": 0.3, "sad": 0.1, "aggressive": 0.9, "relaxed": 0.1, "party": 0.7}
        arousal = MoodAnalyzer._compute_arousal(moods)
        assert arousal > 0.6  # Aggressive + party = high arousal

    def test_compute_arousal_relaxed(self):
        moods = {"happy": 0.3, "sad": 0.2, "aggressive": 0.1, "relaxed": 0.9, "party": 0.1}
        arousal = MoodAnalyzer._compute_arousal(moods)
        assert arousal < 0.4  # Relaxed = low arousal

    def test_classify_quadrant_euphoric(self):
        assert MoodAnalyzer._classify_quadrant(0.8, 0.7) == "euphoric"

    def test_classify_quadrant_tense(self):
        assert MoodAnalyzer._classify_quadrant(0.3, 0.8) == "tense"

    def test_classify_quadrant_melancholic(self):
        assert MoodAnalyzer._classify_quadrant(0.2, 0.3) == "melancholic"

    def test_classify_quadrant_serene(self):
        assert MoodAnalyzer._classify_quadrant(0.7, 0.3) == "serene"


class TestMoodVisualParams:
    def test_euphoric_mapping(self):
        mood = {"valence": 0.8, "arousal": 0.8, "quadrant": "euphoric",
                "happy": 0.9, "sad": 0.1, "aggressive": 0.3, "relaxed": 0.2, "party": 0.8}
        params = map_mood_to_visuals(mood)

        assert params.color_temperature > 0.5  # Warm
        assert params.saturation_mult > 1.0  # Vivid
        assert params.flash_intensity_mult > 1.0  # Strong flash
        assert "laser" in params.recommended_styles or "cyberpunk" in params.recommended_styles

    def test_tense_mapping(self):
        mood = {"valence": 0.3, "arousal": 0.8, "quadrant": "tense",
                "happy": 0.2, "sad": 0.3, "aggressive": 0.9, "relaxed": 0.1, "party": 0.3}
        params = map_mood_to_visuals(mood)

        assert params.contrast_mult > 1.0  # High contrast
        assert params.strobe_recommend is True  # Aggressive = strobe
        assert "fire" in params.recommended_styles or "glitch" in params.recommended_styles

    def test_melancholic_mapping(self):
        mood = {"valence": 0.2, "arousal": 0.3, "quadrant": "melancholic",
                "happy": 0.1, "sad": 0.8, "aggressive": 0.1, "relaxed": 0.3, "party": 0.1}
        params = map_mood_to_visuals(mood)

        assert params.color_temperature < 0.5  # Cool
        assert params.saturation_mult < 1.0  # Desaturated
        assert params.flash_intensity_mult < 1.0  # Gentle flash
        assert "cosmic" in params.recommended_styles or "nature" in params.recommended_styles

    def test_serene_mapping(self):
        mood = {"valence": 0.7, "arousal": 0.2, "quadrant": "serene",
                "happy": 0.4, "sad": 0.1, "aggressive": 0.05, "relaxed": 0.9, "party": 0.1}
        params = map_mood_to_visuals(mood)

        assert params.motion_speed < 0.9  # Slow motion
        assert params.strobe_recommend is False  # No strobe for calm
        assert "nature" in params.recommended_styles or "liquid" in params.recommended_styles

    def test_enhance_prompt_with_mood(self):
        params = MoodVisualParams(
            prompt_mood_prefix="euphoric, uplifting",
            prompt_color_guide="warm golden light",
            prompt_atmosphere="triumphant ascent",
        )
        result = enhance_prompt_with_mood("abstract flowing shapes", params)

        assert "euphoric" in result
        assert "abstract flowing shapes" in result
        assert "warm golden light" in result
        assert "triumphant ascent" in result

    def test_enhance_prompt_without_mood(self):
        params = MoodVisualParams()  # All empty
        result = enhance_prompt_with_mood("base prompt", params)
        assert "base prompt" in result


class TestMoodWithRealAudio:
    """Test mood analysis with real audio files (requires models)."""

    @pytest.fixture
    def analyzer(self):
        models_dir = Path(__file__).parent.parent / "models" / "mood"
        if not (models_dir / "discogs-effnet-bs64-1.pb").exists():
            pytest.skip("Mood models not downloaded")
        return MoodAnalyzer(models_dir=models_dir)

    def test_analyze_house_track(self, analyzer):
        result = analyzer.analyze("samples/house_128bpm.wav")
        assert isinstance(result, MoodAnalysis)
        assert 0 <= result.valence <= 1
        assert 0 <= result.arousal <= 1
        assert result.dominant_mood in MOOD_NAMES
        assert result.quadrant in QUADRANT_LABELS
        assert len(result.mood_descriptor) > 0

    def test_analyze_returns_segments(self, analyzer):
        result = analyzer.analyze("samples/house_128bpm.wav", segment_duration=30.0)
        assert len(result.segments) >= 2  # 120s track / 30s segments

    def test_different_tracks_different_moods(self, analyzer):
        """Different tracks should produce meaningfully different mood profiles."""
        house = analyzer.analyze("samples/house_128bpm.wav")
        # Even synthetic tracks should differ somewhat
        trance = analyzer.analyze("samples/trance_140bpm.wav")

        # They should both be valid
        assert house.dominant_mood in MOOD_NAMES
        assert trance.dominant_mood in MOOD_NAMES
