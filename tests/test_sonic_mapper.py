"""Tests for sonic-to-visual mapper (src/analyzer/sonic_mapper.py)."""
import pytest
import numpy as np

from src.analyzer.sonic_mapper import (
    SegmentSonicProfile,
    analyze_segment_sonics,
    enhance_segment_prompt,
    create_segment_sonic_profiles,
    STEM_VISUAL_LANGUAGE,
    EYE_REACTIONS,
)


# ---------------------------------------------------------------------------
# Helpers — mock timeline data simulating real stem analysis output
# ---------------------------------------------------------------------------

def _make_timeline(
    duration: float = 10.0,
    fps: float = 30.0,
    events: list[dict] | None = None,
    drums_energy: float = 0.5,
    bass_energy: float = 0.4,
    synth_energy: float = 0.3,
    vocals_energy: float = 0.1,
) -> dict:
    """Build a mock event timeline matching create_event_timeline() output."""
    total_frames = int(duration * fps)

    per_frame_stems = {
        "drums": {
            "energy": [drums_energy] * total_frames,
            "brightness": [0.5] * total_frames,
        },
        "bass": {
            "energy": [bass_energy] * total_frames,
            "brightness": [0.3] * total_frames,
        },
        "other": {
            "energy": [synth_energy] * total_frames,
            "brightness": [0.6] * total_frames,
        },
        "vocals": {
            "energy": [vocals_energy] * total_frames,
            "brightness": [0.4] * total_frames,
        },
    }

    if events is None:
        events = []

    return {
        "audio_file": "test_track.wav",
        "duration": duration,
        "sample_rate": 44100,
        "stems": ["drums", "bass", "other", "vocals"],
        "events": events,
        "per_frame_data": {
            "fps": fps,
            "total_frames": total_frames,
            "stems": per_frame_stems,
        },
        "summary": {
            "total_events": len(events),
            "events_per_stem": {},
        },
    }


def _event(time: float, stem: str, event_type: str,
           spectral_character: str = "clean", intensity: float = 0.8) -> dict:
    """Shorthand for a single event dict."""
    return {
        "time": time,
        "duration": 0.1,
        "stem": stem,
        "event_type": event_type,
        "intensity": intensity,
        "frequency_band": "mid",
        "spectral_character": spectral_character,
        "description": f"{stem} {event_type}",
    }


# ---------------------------------------------------------------------------
# Tests: SegmentSonicProfile dataclass
# ---------------------------------------------------------------------------

class TestSegmentSonicProfile:
    def test_defaults(self):
        p = SegmentSonicProfile(start_time=0, end_time=10, duration=10)
        assert p.drums_energy == 0.0
        assert p.bass_energy == 0.0
        assert p.synth_energy == 0.0
        assert p.vocals_energy == 0.0
        assert p.dominant_stem == "drums"
        assert p.has_vocal is False
        assert p.has_synth_stab is False
        assert p.has_bass_drop is False
        assert p.has_drum_break is False
        assert p.synth_character == "clean"


# ---------------------------------------------------------------------------
# Tests: analyze_segment_sonics
# ---------------------------------------------------------------------------

class TestAnalyzeSegmentSonics:

    def test_basic_profile_fields(self):
        timeline = _make_timeline(duration=10.0)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.start_time == 0.0
        assert profile.end_time == 10.0
        assert profile.duration == 10.0

    def test_energy_averages_from_per_frame(self):
        timeline = _make_timeline(
            drums_energy=0.7, bass_energy=0.5,
            synth_energy=0.3, vocals_energy=0.1,
        )
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert abs(profile.drums_energy - 0.7) < 0.01
        assert abs(profile.bass_energy - 0.5) < 0.01
        assert abs(profile.synth_energy - 0.3) < 0.01
        assert abs(profile.vocals_energy - 0.1) < 0.01

    def test_dominant_stem_detection(self):
        timeline = _make_timeline(
            drums_energy=0.2, bass_energy=0.9,
            synth_energy=0.1, vocals_energy=0.0,
        )
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.dominant_stem == "bass"

    def test_detects_synth_stab(self):
        events = [_event(2.0, "other", "stab")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.has_synth_stab is True

    def test_detects_bass_drop(self):
        events = [_event(5.0, "bass", "drop")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.has_bass_drop is True

    def test_detects_vocal_presence(self):
        events = [_event(3.0, "vocals", "onset")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.has_vocal is True

    def test_detects_vocal_sustained(self):
        events = [_event(3.0, "vocals", "sustained")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.has_vocal is True

    def test_detects_drum_break_buildup(self):
        events = [_event(1.0, "drums", "buildup")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.has_drum_break is True

    def test_detects_drum_break_drop(self):
        events = [_event(1.0, "drums", "drop")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.has_drum_break is True

    def test_detects_riser(self):
        events = [_event(2.0, "other", "buildup")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.has_riser is True

    def test_detects_silence_moment(self):
        events = [_event(4.0, "drums", "silence")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.has_silence_moment is True

    def test_filters_events_by_time_range(self):
        events = [
            _event(2.0, "bass", "drop"),   # inside 0-5
            _event(7.0, "bass", "drop"),   # outside 0-5
        ]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 5.0)
        assert profile.has_bass_drop is True
        assert profile.event_count == 1

    def test_event_count(self):
        events = [
            _event(1.0, "drums", "stab"),
            _event(2.0, "bass", "onset"),
            _event(3.0, "other", "stab"),
        ]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.event_count == 3


class TestSpectralCharacterDetection:

    def test_gritty_synth(self):
        events = [_event(1.0, "other", "stab", spectral_character="gritty")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.synth_character == "gritty"

    def test_bright_synth(self):
        events = [_event(1.0, "other", "onset", spectral_character="bright")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.synth_character == "bright"

    def test_gritty_overrides_bright(self):
        """Gritty character should take precedence over bright."""
        events = [
            _event(1.0, "other", "onset", spectral_character="bright"),
            _event(2.0, "other", "stab", spectral_character="gritty"),
        ]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.synth_character == "gritty"

    def test_default_clean_character(self):
        timeline = _make_timeline(events=[])
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.synth_character == "clean"


class TestEnergyLevelDescriptions:

    def test_maximum_intensity(self):
        """Total energy > 2.5 should trigger maximum intensity description."""
        timeline = _make_timeline(
            drums_energy=0.8, bass_energy=0.7,
            synth_energy=0.6, vocals_energy=0.5,
        )
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "maximum sonic intensity" in profile.sonic_prompt

    def test_high_energy(self):
        """Total energy > 1.5 should trigger high energy description."""
        timeline = _make_timeline(
            drums_energy=0.5, bass_energy=0.4,
            synth_energy=0.4, vocals_energy=0.3,
        )
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "high energy" in profile.sonic_prompt

    def test_moderate_energy(self):
        """Total energy > 0.8 should trigger moderate description."""
        timeline = _make_timeline(
            drums_energy=0.3, bass_energy=0.2,
            synth_energy=0.2, vocals_energy=0.2,
        )
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "moderate energy" in profile.sonic_prompt

    def test_sparse_energy(self):
        """Total energy <= 0.8 should trigger sparse description."""
        timeline = _make_timeline(
            drums_energy=0.1, bass_energy=0.1,
            synth_energy=0.1, vocals_energy=0.1,
        )
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "sparse" in profile.sonic_prompt


class TestSonicPromptGeneration:

    def test_bass_drop_in_prompt(self):
        events = [_event(2.0, "bass", "drop")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "bass drop" in profile.sonic_prompt.lower()

    def test_gritty_stab_in_prompt(self):
        events = [_event(1.0, "other", "stab", spectral_character="gritty")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "gritty" in profile.sonic_prompt.lower()

    def test_bright_stab_in_prompt(self):
        events = [_event(1.0, "other", "stab", spectral_character="bright")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "bright" in profile.sonic_prompt.lower()

    def test_riser_in_prompt(self):
        events = [_event(2.0, "other", "buildup")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "rising" in profile.sonic_prompt.lower() or "tension" in profile.sonic_prompt.lower()

    def test_drum_break_in_prompt(self):
        events = [_event(1.0, "drums", "drop")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "drum" in profile.sonic_prompt.lower()

    def test_vocal_in_prompt(self):
        events = [_event(3.0, "vocals", "onset")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "vocal" in profile.sonic_prompt.lower()

    def test_silence_in_prompt(self):
        events = [_event(4.0, "drums", "silence")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "silence" in profile.sonic_prompt.lower()

    def test_heavy_drums_in_prompt(self):
        timeline = _make_timeline(drums_energy=0.8)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "percussive" in profile.sonic_prompt.lower() or "drums" in profile.sonic_prompt.lower()

    def test_deep_bass_in_prompt(self):
        timeline = _make_timeline(bass_energy=0.8)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "bass" in profile.sonic_prompt.lower()

    def test_synth_presence_in_prompt(self):
        timeline = _make_timeline(synth_energy=0.6)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "synth" in profile.sonic_prompt.lower()


class TestEyePromptGeneration:

    def test_bass_drop_eye_reaction(self):
        events = [_event(2.0, "bass", "drop")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.eye_prompt != ""
        assert "eye" in profile.eye_prompt.lower() or "iris" in profile.eye_prompt.lower()

    def test_gritty_stab_eye_reaction(self):
        events = [_event(1.0, "other", "stab", spectral_character="gritty")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "eye" in profile.eye_prompt.lower() or "iris" in profile.eye_prompt.lower()

    def test_vocal_onset_eye_reaction(self):
        events = [_event(3.0, "vocals", "onset")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "eye" in profile.eye_prompt.lower()

    def test_no_eyes_for_empty_segment(self):
        timeline = _make_timeline(
            events=[],
            drums_energy=0.1, bass_energy=0.1,
            synth_energy=0.1, vocals_energy=0.1,
        )
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert profile.eye_prompt == ""

    def test_riser_eye_reaction(self):
        events = [_event(2.0, "other", "buildup")]
        timeline = _make_timeline(events=events)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "eye" in profile.eye_prompt.lower()

    def test_bass_sustained_eye_reaction(self):
        """High bass energy triggers bass_sustained eye reaction."""
        timeline = _make_timeline(bass_energy=0.8)
        profile = analyze_segment_sonics(timeline, 0.0, 10.0)
        assert "eye" in profile.eye_prompt.lower()


# ---------------------------------------------------------------------------
# Tests: enhance_segment_prompt
# ---------------------------------------------------------------------------

class TestEnhanceSegmentPrompt:

    def test_appends_sonic_info(self):
        profile = SegmentSonicProfile(
            start_time=0, end_time=10, duration=10,
            sonic_prompt="massive bass drop, heavy drums",
            eye_prompt="eyes dilate on impact",
        )
        result = enhance_segment_prompt("peaceful greenhouse, 8-bit pixel art", profile)
        assert "peaceful greenhouse" in result
        assert "Music energy:" in result
        assert "massive bass drop" in result
        assert "Eye reactions:" in result
        assert "eyes dilate" in result

    def test_no_sonic_data_returns_base(self):
        profile = SegmentSonicProfile(
            start_time=0, end_time=10, duration=10,
            sonic_prompt="", eye_prompt="",
        )
        result = enhance_segment_prompt("base prompt only", profile)
        assert result == "base prompt only"

    def test_exclude_eyes(self):
        profile = SegmentSonicProfile(
            start_time=0, end_time=10, duration=10,
            sonic_prompt="big bass",
            eye_prompt="eyes go wide",
        )
        result = enhance_segment_prompt("base", profile, include_eyes=False)
        assert "Music energy:" in result
        assert "Eye reactions:" not in result

    def test_sonic_only_no_eyes(self):
        profile = SegmentSonicProfile(
            start_time=0, end_time=10, duration=10,
            sonic_prompt="drums heavy",
            eye_prompt="",
        )
        result = enhance_segment_prompt("base", profile)
        assert "Music energy:" in result
        assert "Eye reactions:" not in result


# ---------------------------------------------------------------------------
# Tests: create_segment_sonic_profiles
# ---------------------------------------------------------------------------

class TestCreateSegmentSonicProfiles:

    def test_one_profile_per_segment(self):
        timeline = _make_timeline(duration=30.0)
        segments = [
            {"start": 0.0, "end": 10.0},
            {"start": 10.0, "end": 20.0},
            {"start": 20.0, "end": 30.0},
        ]
        profiles = create_segment_sonic_profiles(timeline, segments)
        assert len(profiles) == 3

    def test_profiles_have_correct_time_ranges(self):
        timeline = _make_timeline(duration=20.0)
        segments = [
            {"start": 0.0, "end": 8.0},
            {"start": 8.0, "end": 20.0},
        ]
        profiles = create_segment_sonic_profiles(timeline, segments)
        assert profiles[0].start_time == 0.0
        assert profiles[0].end_time == 8.0
        assert profiles[1].start_time == 8.0
        assert profiles[1].end_time == 20.0

    def test_supports_start_time_end_time_keys(self):
        """Segments can use start_time/end_time instead of start/end."""
        timeline = _make_timeline(duration=10.0)
        segments = [{"start_time": 0.0, "end_time": 10.0}]
        profiles = create_segment_sonic_profiles(timeline, segments)
        assert len(profiles) == 1
        assert profiles[0].start_time == 0.0
        assert profiles[0].end_time == 10.0

    def test_events_distributed_across_segments(self):
        events = [
            _event(2.0, "bass", "drop"),
            _event(12.0, "other", "stab"),
        ]
        timeline = _make_timeline(duration=20.0, events=events)
        segments = [
            {"start": 0.0, "end": 10.0},
            {"start": 10.0, "end": 20.0},
        ]
        profiles = create_segment_sonic_profiles(timeline, segments)
        assert profiles[0].has_bass_drop is True
        assert profiles[0].has_synth_stab is False
        assert profiles[1].has_bass_drop is False
        assert profiles[1].has_synth_stab is True

    def test_empty_segments_list(self):
        timeline = _make_timeline()
        profiles = create_segment_sonic_profiles(timeline, [])
        assert profiles == []

    def test_each_profile_has_sonic_prompt(self):
        events = [
            _event(1.0, "drums", "stab"),
            _event(5.0, "bass", "drop"),
            _event(15.0, "vocals", "onset"),
        ]
        timeline = _make_timeline(duration=20.0, events=events)
        segments = [
            {"start": 0.0, "end": 10.0},
            {"start": 10.0, "end": 20.0},
        ]
        profiles = create_segment_sonic_profiles(timeline, segments)
        for p in profiles:
            assert isinstance(p.sonic_prompt, str)
            assert len(p.sonic_prompt) > 0


# ---------------------------------------------------------------------------
# Tests: constant maps
# ---------------------------------------------------------------------------

class TestConstantMaps:

    def test_all_stems_in_visual_language(self):
        assert set(STEM_VISUAL_LANGUAGE.keys()) == {"drums", "bass", "other", "vocals"}

    def test_eye_reactions_not_empty(self):
        assert len(EYE_REACTIONS) > 0
        for key, value in EYE_REACTIONS.items():
            assert isinstance(value, str)
            assert len(value) > 0

    def test_eye_reactions_reference_valid_stems(self):
        valid_stems = {"drums", "bass", "other", "vocals"}
        for key in EYE_REACTIONS:
            stem = key.split("_")[0]
            assert stem in valid_stems, f"EYE_REACTIONS key '{key}' references unknown stem '{stem}'"
