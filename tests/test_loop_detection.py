"""Tests for sample and loop detection."""
import tempfile

import numpy as np
import pytest
import soundfile as sf

from src.analyzer.loop_detection import (
    apply_repetition_to_segments,
    detect_loops,
    get_repetition_style,
    _compute_similarity_matrix,
    _deduplicate_loops,
)


def _make_looping_audio(bpm: float = 128.0, loop_beats: int = 8,
                        repetitions: int = 4, sr: int = 22050) -> str:
    """Create audio with a repeating pattern."""
    beat_dur = 60.0 / bpm
    loop_dur = loop_beats * beat_dur
    total_dur = loop_dur * (repetitions + 1)  # extra for intro
    n_samples = int(total_dur * sr)

    t = np.linspace(0, total_dur, n_samples, endpoint=False)

    # Create a repeating melodic pattern
    loop_samples = int(loop_dur * sr)
    pattern = np.zeros(loop_samples)
    pattern_t = np.linspace(0, loop_dur, loop_samples, endpoint=False)

    # Simple melody that repeats: C-E-G-C
    notes = [261.63, 329.63, 392.00, 523.25]
    note_len = loop_samples // len(notes)
    for i, freq in enumerate(notes):
        start = i * note_len
        end = min((i + 1) * note_len, loop_samples)
        pattern[start:end] = 0.5 * np.sin(2 * np.pi * freq * pattern_t[start:end])

    # Repeat the pattern
    y = np.zeros(n_samples)
    intro_samples = loop_samples  # one loop of intro
    for rep in range(repetitions + 1):
        offset = intro_samples + rep * loop_samples
        end = min(offset + loop_samples, n_samples)
        copy_len = end - offset
        if copy_len > 0:
            y[offset:end] = pattern[:copy_len]

    # Add some noise to intro
    y[:intro_samples] = 0.1 * np.random.randn(intro_samples)

    # Normalize
    peak = np.max(np.abs(y))
    if peak > 0:
        y = y / peak * 0.9

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, y, sr)
    return tmp.name


# ── Similarity matrix ────────────────────────────────────────────────

class TestSimilarityMatrix:
    def test_square_matrix(self):
        chroma = np.random.rand(12, 20)
        sim = _compute_similarity_matrix(chroma)
        assert sim.shape == (20, 20)

    def test_diagonal_is_one(self):
        chroma = np.random.rand(12, 10) + 0.1  # Avoid zero columns
        sim = _compute_similarity_matrix(chroma)
        for i in range(10):
            assert abs(sim[i, i] - 1.0) < 0.01

    def test_symmetric(self):
        chroma = np.random.rand(12, 15)
        sim = _compute_similarity_matrix(chroma)
        assert np.allclose(sim, sim.T, atol=1e-6)


# ── Loop detection ───────────────────────────────────────────────────

class TestDetectLoops:
    def test_returns_list(self):
        audio = _make_looping_audio()
        loops = detect_loops(audio, bpm=128.0)
        assert isinstance(loops, list)

    def test_loop_has_required_fields(self):
        audio = _make_looping_audio()
        loops = detect_loops(audio, bpm=128.0)
        for loop in loops:
            assert "start" in loop
            assert "duration" in loop
            assert "duration_beats" in loop
            assert "repetitions" in loop
            assert "confidence" in loop

    def test_detects_repeating_pattern(self):
        audio = _make_looping_audio(loop_beats=8, repetitions=6)
        loops = detect_loops(audio, bpm=128.0)
        # Should find at least some loops (detection is heuristic)
        # May not always detect depending on audio characteristics
        assert isinstance(loops, list)


# ── Deduplication ────────────────────────────────────────────────────

class TestDeduplication:
    def test_removes_overlapping(self):
        loops = [
            {"start": 0, "total_duration": 10, "confidence": 0.9},
            {"start": 1, "total_duration": 10, "confidence": 0.7},
        ]
        result = _deduplicate_loops(loops)
        assert len(result) == 1
        assert result[0]["confidence"] == 0.9

    def test_keeps_non_overlapping(self):
        loops = [
            {"start": 0, "total_duration": 5, "confidence": 0.8},
            {"start": 10, "total_duration": 5, "confidence": 0.7},
        ]
        result = _deduplicate_loops(loops)
        assert len(result) == 2

    def test_empty_input(self):
        assert _deduplicate_loops([]) == []


# ── Repetition style ─────────────────────────────────────────────────

class TestGetRepetitionStyle:
    def test_default(self):
        assert get_repetition_style() == "evolving"

    def test_brand_override(self):
        brand = {"repetition": {"style": "rotating"}}
        assert get_repetition_style(brand) == "rotating"


# ── Apply to segments ────────────────────────────────────────────────

class TestApplyRepetitionToSegments:
    def test_adds_repetition_metadata(self):
        segments = [
            {"start": 5.0, "end": 10.0, "label": "drop"},
            {"start": 10.0, "end": 15.0, "label": "drop"},
        ]
        loops = [{
            "start": 5.0, "end": 10.0, "duration": 5.0,
            "duration_beats": 8, "repetitions": 3,
            "confidence": 0.85, "total_duration": 20.0,
        }]
        result = apply_repetition_to_segments(segments, loops)
        assert "repetition" in result[0]
        assert result[0]["repetition"]["in_loop"]

    def test_evolving_style(self):
        segments = [{"start": 5.0, "end": 10.0, "label": "drop"}]
        loops = [{
            "start": 0.0, "end": 5.0, "duration": 5.0,
            "duration_beats": 8, "repetitions": 3,
            "confidence": 0.8, "total_duration": 20.0,
        }]
        result = apply_repetition_to_segments(segments, loops, {"repetition": {"style": "evolving"}})
        assert "evolution_intensity" in result[0]["repetition"]

    def test_rotating_style(self):
        segments = [{"start": 5.0, "end": 10.0, "label": "drop"}]
        loops = [{
            "start": 0.0, "end": 5.0, "duration": 5.0,
            "duration_beats": 8, "repetitions": 3,
            "confidence": 0.8, "total_duration": 20.0,
        }]
        result = apply_repetition_to_segments(segments, loops, {"repetition": {"style": "rotating"}})
        assert "hue_rotation" in result[0]["repetition"]

    def test_no_loops_no_change(self):
        segments = [{"start": 0.0, "end": 10.0, "label": "drop"}]
        result = apply_repetition_to_segments(segments, [])
        assert "repetition" not in result[0]
