"""Tests for the music analysis pipeline."""
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.analyzer.audio import analyze_track, TrackAnalysis


def _make_test_audio(bpm: float = 128.0, duration: float = 30.0, sr: int = 22050) -> str:
    """Generate a test audio file with clicks at the given BPM."""
    n_samples = int(duration * sr)
    y = np.zeros(n_samples)

    beat_interval = int(60.0 / bpm * sr)
    click_len = int(0.01 * sr)

    # Generate clicks at beat positions with varying intensity
    for i in range(0, n_samples, beat_interval):
        beat_num = i // beat_interval
        # Downbeats (every 4) are louder
        amplitude = 0.8 if beat_num % 4 == 0 else 0.4
        end = min(i + click_len, n_samples)
        y[i:end] = amplitude * np.sin(2 * np.pi * 1000 * np.arange(end - i) / sr)

    # Add some sustained tone for energy variation
    # First half: lower energy
    mid = n_samples // 2
    t = np.arange(mid) / sr
    y[:mid] += 0.1 * np.sin(2 * np.pi * 200 * t)
    # Second half: higher energy
    t = np.arange(n_samples - mid) / sr
    y[mid:] += 0.3 * np.sin(2 * np.pi * 200 * t) + 0.2 * np.sin(2 * np.pi * 400 * t)

    # Write to temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, y, sr)
    return tmp.name


def test_analyze_basic():
    """Test basic analysis of a synthetic track."""
    audio_path = _make_test_audio(bpm=128.0, duration=30.0)
    analysis = analyze_track(audio_path)

    assert isinstance(analysis, TrackAnalysis)
    assert analysis.duration > 25.0
    assert analysis.duration < 35.0
    # BPM should be close to 128
    assert abs(analysis.bpm - 128.0) < 10.0
    assert analysis.time_signature == 4
    assert len(analysis.beats) > 0
    assert len(analysis.phrases) > 0
    assert len(analysis.energy_envelope) > 0

    # Beats should have time and strength
    for beat in analysis.beats:
        assert beat.time >= 0
        assert 0 <= beat.strength <= 1.0


def test_phrase_labels():
    """Test that phrases get meaningful labels."""
    audio_path = _make_test_audio(bpm=128.0, duration=60.0)
    analysis = analyze_track(audio_path)

    valid_labels = {"intro", "buildup", "drop", "breakdown", "outro"}
    for phrase in analysis.phrases:
        assert phrase.label in valid_labels, f"Invalid label: {phrase.label}"
        assert phrase.start < phrase.end
        assert phrase.beats > 0
        assert 0 <= phrase.energy <= 1.0


def test_json_serialization():
    """Test that analysis can be serialized to JSON."""
    audio_path = _make_test_audio(bpm=140.0, duration=20.0)
    analysis = analyze_track(audio_path)

    json_str = analysis.to_json()
    data = json.loads(json_str)

    assert "bpm" in data
    assert "beats" in data
    assert "phrases" in data
    assert isinstance(data["beats"], list)


def test_different_bpms():
    """Test analysis at different tempos."""
    for target_bpm in [120.0, 140.0, 174.0]:
        audio_path = _make_test_audio(bpm=target_bpm, duration=20.0)
        analysis = analyze_track(audio_path)
        # BPM detection should be within 15% or detect a harmonic
        ratio = analysis.bpm / target_bpm
        assert (0.45 < ratio < 1.15) or (1.85 < ratio < 2.15), \
            f"BPM {analysis.bpm} too far from target {target_bpm}"


def test_to_dict():
    """Test dict conversion."""
    audio_path = _make_test_audio(bpm=128.0, duration=15.0)
    analysis = analyze_track(audio_path)
    d = analysis.to_dict()

    assert d["bpm"] == analysis.bpm
    assert d["duration"] == analysis.duration
    assert len(d["phrases"]) == len(analysis.phrases)
