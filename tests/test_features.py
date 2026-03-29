"""Tests for extended feature extraction (src/analyzer/features.py)."""
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.analyzer.features import VisualFeatures, extract_features


def _make_audio(duration: float = 5.0, sr: int = 22050) -> str:
    """Create a synthetic test audio file."""
    n = int(duration * sr)
    t = np.arange(n) / sr

    # Simple beat pattern + tonal content
    beat_samples = int(60.0 / 128.0 * sr)
    click_len = int(0.005 * sr)
    y = np.zeros(n)
    for i in range(0, n, beat_samples):
        end = min(i + click_len, n)
        y[i:end] = 0.8 * np.sin(2 * np.pi * 800 * np.arange(end - i) / sr)

    # Add tonal content (melody-like)
    y += 0.3 * np.sin(2 * np.pi * 440 * t)
    y = np.clip(y, -1.0, 1.0)

    path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    sf.write(path, y, sr)
    return path


class TestExtractFeatures:
    def test_returns_visual_features(self):
        audio_path = _make_audio()
        features = extract_features(audio_path)
        assert isinstance(features, VisualFeatures)

    def test_beat_intensity_normalized(self):
        audio_path = _make_audio()
        features = extract_features(audio_path)
        assert len(features.beat_intensity) > 0
        assert all(0.0 <= v <= 1.0 for v in features.beat_intensity)

    def test_beat_brightness_normalized(self):
        audio_path = _make_audio()
        features = extract_features(audio_path)
        assert len(features.beat_brightness) > 0
        assert all(0.0 <= v <= 1.0 for v in features.beat_brightness)

    def test_beat_warmth_normalized(self):
        audio_path = _make_audio()
        features = extract_features(audio_path)
        assert len(features.beat_warmth) > 0
        assert all(0.0 <= v <= 1.0 for v in features.beat_warmth)

    def test_overall_energy_in_range(self):
        audio_path = _make_audio()
        features = extract_features(audio_path)
        assert 0.0 <= features.overall_energy <= 1.0

    def test_overall_brightness_in_range(self):
        audio_path = _make_audio()
        features = extract_features(audio_path)
        assert 0.0 <= features.overall_brightness <= 1.0

    def test_has_vocals_is_bool(self):
        audio_path = _make_audio()
        features = extract_features(audio_path)
        assert isinstance(features.has_vocals, bool)

    def test_phrase_mood_values(self):
        audio_path = _make_audio(duration=10.0)
        features = extract_features(audio_path)
        valid_moods = {"dark", "bright", "intense", "calm"}
        for mood in features.phrase_mood:
            assert mood in valid_moods

    def test_phrase_complexity_normalized(self):
        audio_path = _make_audio(duration=10.0)
        features = extract_features(audio_path)
        if features.phrase_complexity:
            assert all(0.0 <= v <= 1.0 for v in features.phrase_complexity)
