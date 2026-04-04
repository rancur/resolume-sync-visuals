"""Tests for rich track metadata generation."""
import json
from pathlib import Path

import pytest

import importlib.util as _ilu

# Import directly to avoid __init__.py pulling in engine.py (which uses
# Python 3.10+ union syntax on 3.9).
_spec = _ilu.spec_from_file_location(
    "metadata",
    str(Path(__file__).resolve().parent.parent / "src" / "generator" / "metadata.py"),
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

generate_track_metadata = _mod.generate_track_metadata
save_metadata = _mod.save_metadata
_extract_track_info = _mod._extract_track_info
_extract_phrase_timeline = _mod._extract_phrase_timeline
_extract_energy_curve = _mod._extract_energy_curve
_extract_mood = _mod._extract_mood
_extract_segments = _mod._extract_segments
_extract_stems = _mod._extract_stems
_extract_cost_breakdown = _mod._extract_cost_breakdown


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_analysis():
    return {
        "title": "Shenlong",
        "artist": "Sub Focus",
        "bpm": 175,
        "duration": 240.5,
        "genre": "DnB",
        "key": "Am",
        "phrases": [
            {"start": 0, "end": 32, "duration": 32, "label": "intro", "energy": 0.3},
            {"start": 32, "end": 64, "duration": 32, "label": "buildup", "energy": 0.6},
            {"start": 64, "end": 128, "duration": 64, "label": "drop", "energy": 0.95},
            {"start": 128, "end": 160, "duration": 32, "label": "breakdown", "energy": 0.4},
            {"start": 160, "end": 224, "duration": 64, "label": "drop", "energy": 0.9},
            {"start": 224, "end": 240.5, "duration": 16.5, "label": "outro", "energy": 0.2},
        ],
    }


@pytest.fixture
def sample_mood():
    return {
        "valence": 0.7,
        "arousal": 0.85,
        "quadrant": "high_energy_positive",
        "tags": ["energetic", "euphoric", "driving"],
    }


@pytest.fixture
def sample_sonic_timeline():
    return {
        "energy_curve": [
            {"time": 0, "energy": 0.3},
            {"time": 32, "energy": 0.6},
            {"time": 64, "energy": 0.95},
            {"time": 128, "energy": 0.4},
            {"time": 160, "energy": 0.9},
            {"time": 224, "energy": 0.2},
        ],
        "stems": {
            "drums": {"energy": 0.85, "presence": 0.9},
            "bass": {"energy": 0.92, "presence": 0.88},
            "vocals": {"energy": 0.3, "presence": 0.2},
            "other": {"energy": 0.7, "presence": 0.75},
        },
    }


@pytest.fixture
def sample_generation_info():
    return {
        "model": "kling-v1",
        "quality": "high",
        "total_cost": 3.45,
        "keyframe_cost": 0.60,
        "video_cost": 2.85,
        "duration_secs": 180,
        "segments": [
            {"index": 0, "label": "intro", "start": 0, "end": 32, "prompt": "Abstract forms emerging", "model": "kling-v1", "cost": 0.45, "cached": False},
            {"index": 1, "label": "buildup", "start": 32, "end": 64, "prompt": "Energy rising", "model": "kling-v1", "cost": 0.50, "cached": False},
            {"index": 2, "label": "drop", "start": 64, "end": 128, "prompt": "Explosive visuals", "model": "kling-v1", "cost": 0.95, "cached": False},
        ],
    }


# ---------------------------------------------------------------------------
# Track info tests
# ---------------------------------------------------------------------------

class TestExtractTrackInfo:
    def test_full_info(self, sample_analysis):
        info = _extract_track_info(sample_analysis)
        assert info["title"] == "Shenlong"
        assert info["artist"] == "Sub Focus"
        assert info["bpm"] == 175
        assert info["duration"] == 240.5
        assert info["genre"] == "DnB"
        assert info["key"] == "Am"

    def test_missing_fields(self):
        info = _extract_track_info({})
        assert info["title"] == "Unknown"
        assert info["artist"] == "Unknown"
        assert info["bpm"] == 0


# ---------------------------------------------------------------------------
# Phrase timeline tests
# ---------------------------------------------------------------------------

class TestExtractPhraseTimeline:
    def test_phrases_extracted(self, sample_analysis):
        timeline = _extract_phrase_timeline(sample_analysis)
        assert len(timeline) == 6
        assert timeline[0]["label"] == "intro"
        assert timeline[2]["label"] == "drop"
        assert timeline[2]["energy"] == 0.95

    def test_empty_analysis(self):
        assert _extract_phrase_timeline({}) == []

    def test_sections_key_fallback(self):
        analysis = {"sections": [{"start": 0, "end": 30, "type": "intro"}]}
        timeline = _extract_phrase_timeline(analysis)
        assert len(timeline) == 1
        assert timeline[0]["label"] == "intro"

    def test_duration_computed(self):
        analysis = {"phrases": [{"start": 10, "end": 42, "label": "drop", "energy": 0.9}]}
        timeline = _extract_phrase_timeline(analysis)
        assert timeline[0]["duration"] == 32


# ---------------------------------------------------------------------------
# Energy curve tests
# ---------------------------------------------------------------------------

class TestExtractEnergyCurve:
    def test_from_sonic_timeline(self, sample_analysis, sample_sonic_timeline):
        curve = _extract_energy_curve(sample_analysis, sample_sonic_timeline)
        assert len(curve) == 6
        assert curve[0]["time"] == 0

    def test_from_analysis(self):
        analysis = {"energy_curve": [{"time": 0, "energy": 0.5}]}
        curve = _extract_energy_curve(analysis, None)
        assert len(curve) == 1

    def test_built_from_phrases(self, sample_analysis):
        curve = _extract_energy_curve(sample_analysis, None)
        assert len(curve) > 0

    def test_empty(self):
        assert _extract_energy_curve({}, None) == []


# ---------------------------------------------------------------------------
# Mood tests
# ---------------------------------------------------------------------------

class TestExtractMood:
    def test_full_mood(self, sample_mood):
        mood = _extract_mood(sample_mood)
        assert mood["valence"] == 0.7
        assert mood["arousal"] == 0.85
        assert mood["quadrant"] == "high_energy_positive"
        assert "energetic" in mood["tags"]

    def test_none_mood(self):
        mood = _extract_mood(None)
        assert mood["quadrant"] == "neutral"
        assert mood["valence"] == 0.5


# ---------------------------------------------------------------------------
# Segments tests
# ---------------------------------------------------------------------------

class TestExtractSegments:
    def test_segments_extracted(self, sample_generation_info):
        segments = _extract_segments(sample_generation_info)
        assert len(segments) == 3
        assert segments[0]["label"] == "intro"
        assert segments[2]["cost"] == 0.95

    def test_none_info(self):
        assert _extract_segments(None) == []


# ---------------------------------------------------------------------------
# Stems tests
# ---------------------------------------------------------------------------

class TestExtractStems:
    def test_from_sonic_timeline(self, sample_sonic_timeline):
        stems = _extract_stems({}, sample_sonic_timeline)
        assert stems["available"] is True
        assert "drums" in stems
        assert stems["drums"]["energy"] == 0.85

    def test_no_stems(self):
        stems = _extract_stems({}, None)
        assert stems["available"] is False


# ---------------------------------------------------------------------------
# Cost breakdown tests
# ---------------------------------------------------------------------------

class TestExtractCostBreakdown:
    def test_full_cost(self, sample_generation_info):
        cost = _extract_cost_breakdown(sample_generation_info)
        assert cost["total"] == 3.45
        assert cost["keyframes"] == 0.60
        assert cost["video"] == 2.85
        assert cost["model"] == "kling-v1"

    def test_none_info(self):
        cost = _extract_cost_breakdown(None)
        assert cost["total"] == 0


# ---------------------------------------------------------------------------
# Full metadata generation
# ---------------------------------------------------------------------------

class TestGenerateTrackMetadata:
    def test_full_metadata(self, sample_analysis, sample_mood, sample_sonic_timeline, sample_generation_info):
        metadata = generate_track_metadata(
            analysis=sample_analysis,
            mood=sample_mood,
            sonic_timeline=sample_sonic_timeline,
            generation_info=sample_generation_info,
        )
        assert metadata["version"] == "1.0"
        assert "generated_at" in metadata
        assert metadata["track"]["title"] == "Shenlong"
        assert len(metadata["phrase_timeline"]) == 6
        assert len(metadata["energy_curve"]) == 6
        assert metadata["mood"]["quadrant"] == "high_energy_positive"
        assert len(metadata["segments"]) == 3
        assert metadata["stems"]["available"] is True
        assert metadata["cost_breakdown"]["total"] == 3.45

    def test_minimal_metadata(self):
        metadata = generate_track_metadata(analysis={"title": "Test", "bpm": 128})
        assert metadata["track"]["title"] == "Test"
        assert metadata["phrase_timeline"] == []
        assert metadata["mood"]["quadrant"] == "neutral"
        assert metadata["segments"] == []


# ---------------------------------------------------------------------------
# Save metadata
# ---------------------------------------------------------------------------

class TestSaveMetadata:
    def test_save_creates_file(self, tmp_path, sample_analysis):
        metadata = generate_track_metadata(analysis=sample_analysis)
        out_path = tmp_path / "metadata.json"
        result = save_metadata(metadata, out_path)
        assert result == out_path
        assert out_path.exists()
        loaded = json.loads(out_path.read_text())
        assert loaded["track"]["title"] == "Shenlong"

    def test_save_creates_parent_dirs(self, tmp_path, sample_analysis):
        metadata = generate_track_metadata(analysis=sample_analysis)
        out_path = tmp_path / "nested" / "deep" / "metadata.json"
        save_metadata(metadata, out_path)
        assert out_path.exists()

    def test_save_is_valid_json(self, tmp_path, sample_analysis, sample_mood, sample_sonic_timeline, sample_generation_info):
        metadata = generate_track_metadata(
            analysis=sample_analysis,
            mood=sample_mood,
            sonic_timeline=sample_sonic_timeline,
            generation_info=sample_generation_info,
        )
        out_path = tmp_path / "metadata.json"
        save_metadata(metadata, out_path)
        # Verify round-trip
        loaded = json.loads(out_path.read_text())
        assert loaded["cost_breakdown"]["total"] == 3.45
        assert len(loaded["segments"]) == 3
