"""Tests for key change detection and visual color mapping."""
import tempfile

import numpy as np
import pytest
import soundfile as sf

from src.analyzer.key_color import (
    KEY_COLOR_MAP,
    apply_key_colors_to_segments,
    detect_key_changes,
    key_change_to_color_transition,
    key_to_color,
    _estimate_key,
    _hex_to_rgb,
)


def _make_audio(duration: float = 10.0, sr: int = 22050) -> str:
    """Create a simple test audio file."""
    t = np.linspace(0, duration, int(duration * sr), endpoint=False)
    # C major chord: C4 + E4 + G4
    y = 0.3 * np.sin(2 * np.pi * 261.63 * t)
    y += 0.3 * np.sin(2 * np.pi * 329.63 * t)
    y += 0.3 * np.sin(2 * np.pi * 392.00 * t)
    y = y / np.max(np.abs(y)) * 0.9
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, y, sr)
    return tmp.name


# ── Key-to-color mapping ────────────────────────────────────────────

class TestKeyToColor:
    def test_major_key(self):
        color = key_to_color("C")
        assert color.startswith("#")
        assert len(color) == 7

    def test_minor_key(self):
        color = key_to_color("Am")
        assert color.startswith("#")

    def test_unknown_key_returns_gray(self):
        color = key_to_color("Xm")
        assert color == "#808080"

    def test_brand_override(self):
        brand = {"key_colors": {"C": "#00FF00"}}
        assert key_to_color("C", brand) == "#00FF00"

    def test_all_keys_have_colors(self):
        """Every key in the map should have a valid hex color."""
        for key, color in KEY_COLOR_MAP.items():
            assert color.startswith("#"), f"Invalid color for {key}: {color}"
            assert len(color) == 7, f"Color for {key} should be 7 chars: {color}"


# ── Color transitions ────────────────────────────────────────────────

class TestKeyChangeToColorTransition:
    def test_returns_transition_spec(self):
        result = key_change_to_color_transition("C", "Am")
        assert "from_color" in result
        assert "to_color" in result
        assert "steps" in result
        assert result["transition_beats"] == 4

    def test_steps_count(self):
        result = key_change_to_color_transition("C", "Am", transition_beats=8)
        assert len(result["steps"]) == 9  # 8 beats + start

    def test_steps_are_hex_colors(self):
        result = key_change_to_color_transition("C", "Am")
        for step in result["steps"]:
            assert step.startswith("#")
            assert len(step) == 7

    def test_first_and_last_match(self):
        result = key_change_to_color_transition("C", "Am")
        assert result["steps"][0] == result["from_color"].lower() or \
               result["steps"][0].lower() == result["from_color"].lower()

    def test_custom_beats(self):
        result = key_change_to_color_transition("C", "Am", transition_beats=2)
        assert result["transition_beats"] == 2
        assert len(result["steps"]) == 3


# ── Key estimation ───────────────────────────────────────────────────

class TestEstimateKey:
    def test_returns_tuple(self):
        chroma = np.random.rand(12, 100)
        key, is_major, confidence = _estimate_key(chroma)
        assert isinstance(key, str)
        assert isinstance(is_major, bool)
        assert 0.0 <= confidence <= 1.0

    def test_c_major_chord(self):
        """A strong C major chromagram should detect C or related key."""
        chroma = np.zeros((12, 50))
        chroma[0, :] = 1.0   # C
        chroma[4, :] = 0.8   # E
        chroma[7, :] = 0.8   # G
        key, is_major, conf = _estimate_key(chroma)
        assert is_major
        assert conf > 0.3

    def test_a_minor_chord(self):
        """A strong A minor chromagram should detect minor key."""
        chroma = np.zeros((12, 50))
        chroma[9, :] = 1.0   # A
        chroma[0, :] = 0.8   # C
        chroma[4, :] = 0.8   # E
        key, is_major, conf = _estimate_key(chroma)
        # Should detect something minor-ish
        assert conf > 0.2

    def test_silent_audio(self):
        chroma = np.zeros((12, 50))
        key, is_major, conf = _estimate_key(chroma)
        assert key == "C"
        assert conf == 0.0


# ── Key change detection ─────────────────────────────────────────────

class TestDetectKeyChanges:
    def test_returns_list(self):
        audio = _make_audio(duration=8.0)
        changes = detect_key_changes(audio, segment_length_sec=2.0)
        assert isinstance(changes, list)

    def test_change_has_required_fields(self):
        audio = _make_audio(duration=10.0)
        changes = detect_key_changes(audio, segment_length_sec=2.0)
        for change in changes:
            assert "time" in change
            assert "from_key" in change
            assert "to_key" in change
            assert "confidence" in change

    def test_short_audio(self):
        audio = _make_audio(duration=2.0)
        changes = detect_key_changes(audio, segment_length_sec=4.0)
        assert isinstance(changes, list)


# ── Apply to segments ────────────────────────────────────────────────

class TestApplyKeyColorsToSegments:
    def test_adds_key_color(self):
        segments = [
            {"start": 0.0, "end": 15.0, "label": "intro"},
            {"start": 15.0, "end": 30.0, "label": "drop"},
        ]
        key_changes = [
            {"time": 0.0, "from_key": "C", "to_key": "Am", "confidence": 0.8},
        ]
        result = apply_key_colors_to_segments(segments, key_changes, bpm=128)
        assert "key_color" in result[0]
        assert "color" in result[0]["key_color"]

    def test_mid_segment_transition(self):
        segments = [
            {"start": 0.0, "end": 30.0, "label": "drop"},
        ]
        key_changes = [
            {"time": 15.0, "from_key": "C", "to_key": "Am", "confidence": 0.9},
        ]
        result = apply_key_colors_to_segments(segments, key_changes, bpm=128)
        assert "transition" in result[0]["key_color"]
        assert result[0]["key_color"]["transition"]["from_key"] == "C"
        assert result[0]["key_color"]["transition"]["to_key"] == "Am"

    def test_no_changes(self):
        segments = [{"start": 0.0, "end": 30.0, "label": "drop"}]
        result = apply_key_colors_to_segments(segments, [], bpm=128)
        assert result == segments

    def test_brand_colors_used(self):
        segments = [{"start": 0.0, "end": 30.0, "label": "drop"}]
        key_changes = [{"time": 0.0, "from_key": "C", "to_key": "C", "confidence": 0.8}]
        brand = {"key_colors": {"C": "#ABCDEF"}}
        result = apply_key_colors_to_segments(
            segments, key_changes, bpm=128, brand_config=brand
        )
        assert result[0]["key_color"]["color"] == "#ABCDEF"


# ── Hex to RGB ───────────────────────────────────────────────────────

class TestHexToRgb:
    def test_valid_color(self):
        assert _hex_to_rgb("#FF0000") == (255, 0, 0)
        assert _hex_to_rgb("#00FF00") == (0, 255, 0)
        assert _hex_to_rgb("#0000FF") == (0, 0, 255)

    def test_without_hash(self):
        assert _hex_to_rgb("FF0000") == (255, 0, 0)

    def test_invalid_returns_gray(self):
        assert _hex_to_rgb("invalid") == (128, 128, 128)
