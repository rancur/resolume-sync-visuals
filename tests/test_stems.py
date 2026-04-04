"""Tests for audio stem separation and sonic event detection."""
import json
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.analyzer.stems import (
    SonicEvent,
    STEM_NAMES,
    FREQUENCY_BANDS,
    classify_spectral_character,
    find_active_regions,
    analyze_stem,
    detect_sonic_events,
    _compute_band_energies,
    _dominant_frequency_band,
    _resample_to_fps,
    _json_default,
    save_timeline,
)


# Path to test audio
SAMPLES_DIR = Path(__file__).parent.parent / "samples"
TEST_AUDIO = SAMPLES_DIR / "house_128bpm.wav"


class TestSonicEventDataclass:
    def test_sonic_event_fields(self):
        event = SonicEvent(
            time=1.5, duration=0.2, stem="drums", event_type="stab",
            intensity=0.8, frequency_band="mid", spectral_character="bright",
            description="bright drum hit",
        )
        assert event.time == 1.5
        assert event.duration == 0.2
        assert event.stem == "drums"
        assert event.event_type == "stab"
        assert event.intensity == 0.8
        assert event.frequency_band == "mid"
        assert event.spectral_character == "bright"
        assert event.description == "bright drum hit"

    def test_sonic_event_valid_stems(self):
        for stem in STEM_NAMES:
            event = SonicEvent(
                time=0, duration=0, stem=stem, event_type="onset",
                intensity=0, frequency_band="mid", spectral_character="clean",
                description="test",
            )
            assert event.stem == stem


class TestSpectralCharacterClassification:
    def test_bright(self):
        assert classify_spectral_character(5000, 0.1) == "bright"

    def test_dark(self):
        assert classify_spectral_character(1000, 0.1) == "dark"

    def test_gritty(self):
        assert classify_spectral_character(2500, 0.4) == "gritty"

    def test_noisy(self):
        assert classify_spectral_character(3000, 0.7) == "noisy"

    def test_clean(self):
        assert classify_spectral_character(2000, 0.05) == "clean"

    def test_clean_moderate_centroid(self):
        # Moderate centroid, low flatness = clean
        assert classify_spectral_character(2500, 0.05) == "clean"


class TestFrequencyBands:
    def test_all_bands_defined(self):
        expected = {"sub_bass", "bass", "low_mid", "mid", "high_mid", "high"}
        assert set(FREQUENCY_BANDS.keys()) == expected

    def test_bands_cover_spectrum(self):
        # Bands should cover 20Hz to 16kHz without gaps
        all_ranges = sorted(FREQUENCY_BANDS.values())
        assert all_ranges[0][0] == 20
        assert all_ranges[-1][1] == 16000
        for i in range(len(all_ranges) - 1):
            assert all_ranges[i][1] == all_ranges[i + 1][0], \
                f"Gap between {all_ranges[i]} and {all_ranges[i+1]}"

    def test_compute_band_energies(self):
        sr = 22050
        # Generate a 440Hz sine wave (should be in "low_mid" or "mid" band)
        t = np.linspace(0, 1.0, sr, dtype=np.float32)
        audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        energies = _compute_band_energies(audio, sr)
        assert set(energies.keys()) == set(FREQUENCY_BANDS.keys())
        # All values should be 0-1
        for v in energies.values():
            assert 0.0 <= v <= 1.0

    def test_compute_band_energies_short_audio(self):
        energies = _compute_band_energies(np.zeros(100, dtype=np.float32), 22050)
        assert all(v == 0.0 for v in energies.values())


class TestActiveRegionDetection:
    def test_finds_active_region(self):
        # Create RMS with one active region in the middle
        sr = 22050
        hop = 512
        rms = np.zeros(100, dtype=np.float32)
        rms[30:60] = 0.8  # Active from frame 30-60
        regions = find_active_regions(rms, sr, hop, threshold_factor=0.15)
        assert len(regions) >= 1
        # First region should start around frame 30
        start_time = regions[0][0]
        assert start_time > 0

    def test_empty_rms(self):
        regions = find_active_regions(np.array([]), 22050, 512)
        assert regions == []

    def test_all_silent(self):
        rms = np.zeros(100, dtype=np.float32)
        regions = find_active_regions(rms, 22050, 512)
        assert regions == []

    def test_all_active(self):
        rms = np.ones(100, dtype=np.float32)
        regions = find_active_regions(rms, 22050, 512)
        assert len(regions) == 1

    def test_multiple_regions(self):
        rms = np.zeros(200, dtype=np.float32)
        rms[20:40] = 0.9
        rms[100:130] = 0.7
        regions = find_active_regions(rms, 22050, 512, threshold_factor=0.15)
        assert len(regions) >= 2


class TestAnalyzeStem:
    @pytest.fixture
    def sine_audio(self):
        """Generate a 2-second 440Hz sine wave."""
        sr = 22050
        t = np.linspace(0, 2.0, sr * 2, dtype=np.float32)
        audio = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        return audio, sr

    def test_analyze_stem_returns_expected_keys(self, sine_audio):
        audio, sr = sine_audio
        result = analyze_stem(audio, sr, "other")
        expected_keys = {
            "name", "rms", "rms_times", "onsets", "onset_strengths",
            "spectral_centroid", "spectral_flatness", "band_energies",
            "active_regions", "mean_centroid", "mean_flatness",
            "spectral_character", "sr", "hop_length",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_analyze_stem_name(self, sine_audio):
        audio, sr = sine_audio
        result = analyze_stem(audio, sr, "bass")
        assert result["name"] == "bass"

    def test_analyze_stem_rms_normalized(self, sine_audio):
        audio, sr = sine_audio
        result = analyze_stem(audio, sr, "drums")
        rms = result["rms"]
        assert np.max(rms) <= 1.0 + 1e-6
        assert np.min(rms) >= 0.0 - 1e-6

    def test_analyze_stem_spectral_character_valid(self, sine_audio):
        audio, sr = sine_audio
        result = analyze_stem(audio, sr, "other")
        assert result["spectral_character"] in {"bright", "dark", "gritty", "clean", "noisy"}

    def test_analyze_stem_band_energies(self, sine_audio):
        audio, sr = sine_audio
        result = analyze_stem(audio, sr, "other")
        assert set(result["band_energies"].keys()) == set(FREQUENCY_BANDS.keys())


class TestDetectSonicEvents:
    @pytest.fixture
    def drum_analysis(self):
        """Create a mock stem analysis dict for drums with transient-like data."""
        sr = 22050
        hop = 512
        n_frames = 200

        # Create RMS with distinct hits
        rms = np.zeros(n_frames, dtype=np.float32)
        rms[20] = 0.9
        rms[21] = 0.3
        rms[22] = 0.1
        rms[60] = 0.8
        rms[61] = 0.2
        rms[100] = 0.95
        rms[101] = 0.4
        rms[102] = 0.1

        rms_times = np.arange(n_frames) * hop / sr

        return {
            "name": "drums",
            "rms": rms,
            "rms_times": rms_times,
            "onsets": [rms_times[20], rms_times[60], rms_times[100]],
            "onset_strengths": [0.9, 0.8, 0.95],
            "spectral_centroid": np.full(n_frames, 3000.0),
            "spectral_flatness": np.full(n_frames, 0.2),
            "band_energies": {"sub_bass": 0.2, "bass": 0.5, "low_mid": 0.8,
                              "mid": 1.0, "high_mid": 0.6, "high": 0.3},
            "active_regions": [(0.4, 0.6), (1.2, 1.5), (2.2, 2.5)],
            "mean_centroid": 3000.0,
            "mean_flatness": 0.2,
            "spectral_character": "clean",
            "sr": sr,
            "hop_length": hop,
        }

    def test_events_returned(self, drum_analysis):
        events = detect_sonic_events(drum_analysis)
        assert len(events) > 0

    def test_events_have_correct_stem(self, drum_analysis):
        events = detect_sonic_events(drum_analysis)
        for event in events:
            assert event.stem == "drums"

    def test_events_have_valid_types(self, drum_analysis):
        valid_types = {"onset", "stab", "transient", "sustained", "buildup", "drop", "sweep", "silence"}
        events = detect_sonic_events(drum_analysis)
        for event in events:
            assert event.event_type in valid_types, f"Invalid event type: {event.event_type}"

    def test_events_have_valid_intensity(self, drum_analysis):
        events = detect_sonic_events(drum_analysis)
        for event in events:
            assert 0.0 <= event.intensity <= 1.0

    def test_events_have_valid_frequency_band(self, drum_analysis):
        valid_bands = set(FREQUENCY_BANDS.keys())
        events = detect_sonic_events(drum_analysis)
        for event in events:
            assert event.frequency_band in valid_bands

    def test_events_have_valid_spectral_character(self, drum_analysis):
        valid_chars = {"bright", "dark", "gritty", "clean", "noisy"}
        events = detect_sonic_events(drum_analysis)
        for event in events:
            assert event.spectral_character in valid_chars

    def test_events_sorted_by_time(self, drum_analysis):
        events = detect_sonic_events(drum_analysis)
        times = [e.time for e in events]
        assert times == sorted(times)

    def test_silence_detection(self, drum_analysis):
        # Widen the gaps between active regions to be > 1 second
        drum_analysis["active_regions"] = [(0.1, 0.3), (2.0, 2.5), (4.5, 5.0)]
        events = detect_sonic_events(drum_analysis)
        silence_events = [e for e in events if e.event_type == "silence"]
        assert len(silence_events) >= 1

    def test_events_have_description(self, drum_analysis):
        events = detect_sonic_events(drum_analysis)
        for event in events:
            assert isinstance(event.description, str)
            assert len(event.description) > 0


class TestPerFrameResampling:
    def test_resample_to_fps(self):
        values = np.array([0.0, 0.5, 1.0, 0.5, 0.0])
        times = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
        result = _resample_to_fps(values, times, fps=10, total_frames=10)
        assert len(result) == 10
        assert all(isinstance(v, float) for v in result)

    def test_resample_empty(self):
        result = _resample_to_fps(np.array([]), np.array([]), fps=30, total_frames=100)
        assert len(result) == 100
        assert all(v == 0.0 for v in result)

    def test_frame_count_matches_duration(self):
        duration = 10.0
        fps = 30.0
        expected_frames = int(duration * fps)
        values = np.random.rand(500)
        times = np.linspace(0, duration, 500)
        result = _resample_to_fps(values, times, fps, expected_frames)
        assert len(result) == expected_frames


@pytest.mark.requires_demucs
class TestStemSeparation:
    """Tests for stem separation — uses mock to avoid requiring Demucs model download."""

    def test_separate_stems_returns_four_stems(self):
        """Test that separation returns 4 stems with correct names (mocked)."""
        import torch
        sr = 44100
        n_samples = sr * 2  # 2 seconds

        # Mock sources: (1, 4, 2, n_samples) — batch, sources, channels, samples
        mock_sources_np = np.random.randn(1, 4, 2, n_samples).astype(np.float32)
        mock_sources_tensor = torch.from_numpy(mock_sources_np)

        mock_model = MagicMock()
        mock_model.samplerate = sr
        mock_model.sources = ["drums", "bass", "other", "vocals"]
        mock_model.to = MagicMock(return_value=mock_model)

        # Build a waveform tensor (2 channels)
        waveform = torch.randn(2, n_samples)

        with patch("demucs.pretrained.get_model", return_value=mock_model), \
             patch("demucs.apply.apply_model", return_value=mock_sources_tensor), \
             patch("torchaudio.load", return_value=(waveform, sr)):

            from src.analyzer.stems import separate_stems
            stems, out_sr = separate_stems("fake.wav", model_name="htdemucs")

        assert len(stems) == 4
        assert set(stems.keys()) == {"drums", "bass", "other", "vocals"}
        assert out_sr == sr
        for name, audio in stems.items():
            assert isinstance(audio, np.ndarray)
            assert audio.ndim == 1  # mono


class TestCreateEventTimeline:
    """Test the full pipeline with synthetic data (mocked stem separation)."""

    @pytest.fixture
    def mock_timeline(self):
        """Create a timeline from synthetic stems without Demucs."""
        sr = 22050
        duration = 3.0
        n_samples = int(sr * duration)
        fps = 30.0

        # Create synthetic stems
        t = np.linspace(0, duration, n_samples, dtype=np.float32)
        stems = {
            "drums": (0.5 * np.sin(2 * np.pi * 100 * t) *
                      (np.sin(2 * np.pi * 2 * t) > 0).astype(np.float32)),
            "bass": (0.4 * np.sin(2 * np.pi * 60 * t)).astype(np.float32),
            "other": (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32),
            "vocals": (0.2 * np.sin(2 * np.pi * 400 * t) *
                       np.exp(-((t - 1.5) ** 2) / 0.5)).astype(np.float32),
        }

        from src.analyzer.stems import analyze_stem, detect_sonic_events, _resample_to_fps
        from dataclasses import asdict

        total_frames = int(duration * fps)
        all_events = []
        events_per_stem = {}
        per_frame_stems = {}

        for name, audio in stems.items():
            analysis = analyze_stem(audio, sr, name)
            events = detect_sonic_events(analysis)
            all_events.extend(events)
            events_per_stem[name] = len(events)

            rms = analysis["rms"]
            rms_times = analysis["rms_times"]
            centroid = analysis["spectral_centroid"]
            c_max = centroid.max() if len(centroid) > 0 else 1.0
            brightness = centroid / c_max if c_max > 0 else centroid

            per_frame_stems[name] = {
                "energy": _resample_to_fps(rms, rms_times, fps, total_frames),
                "brightness": _resample_to_fps(brightness, rms_times, fps, total_frames),
            }

        all_events.sort(key=lambda e: e.time)

        return {
            "audio_file": "test.wav",
            "duration": duration,
            "sample_rate": sr,
            "stems": list(stems.keys()),
            "events": [asdict(e) for e in all_events],
            "per_frame_data": {
                "fps": fps,
                "total_frames": total_frames,
                "stems": per_frame_stems,
            },
            "summary": {
                "total_events": len(all_events),
                "events_per_stem": events_per_stem,
            },
        }

    def test_timeline_has_four_stems(self, mock_timeline):
        assert len(mock_timeline["stems"]) == 4
        assert set(mock_timeline["stems"]) == {"drums", "bass", "other", "vocals"}

    def test_timeline_has_events(self, mock_timeline):
        assert mock_timeline["summary"]["total_events"] > 0
        assert len(mock_timeline["events"]) == mock_timeline["summary"]["total_events"]

    def test_per_frame_data_frame_count(self, mock_timeline):
        expected = int(mock_timeline["duration"] * mock_timeline["per_frame_data"]["fps"])
        assert mock_timeline["per_frame_data"]["total_frames"] == expected
        for stem_name in mock_timeline["stems"]:
            energy = mock_timeline["per_frame_data"]["stems"][stem_name]["energy"]
            brightness = mock_timeline["per_frame_data"]["stems"][stem_name]["brightness"]
            assert len(energy) == expected
            assert len(brightness) == expected

    def test_events_have_required_fields(self, mock_timeline):
        required = {"time", "duration", "stem", "event_type", "intensity",
                    "frequency_band", "spectral_character", "description"}
        for event in mock_timeline["events"]:
            assert required.issubset(set(event.keys())), \
                f"Missing fields: {required - set(event.keys())}"

    def test_events_per_stem_matches(self, mock_timeline):
        # Count events per stem from the events list
        counted = {}
        for event in mock_timeline["events"]:
            stem = event["stem"]
            counted[stem] = counted.get(stem, 0) + 1
        assert counted == mock_timeline["summary"]["events_per_stem"]

    def test_summary_total_matches_events(self, mock_timeline):
        assert mock_timeline["summary"]["total_events"] == len(mock_timeline["events"])

    def test_per_frame_energy_in_range(self, mock_timeline):
        for stem_name in mock_timeline["stems"]:
            energy = mock_timeline["per_frame_data"]["stems"][stem_name]["energy"]
            for v in energy:
                assert 0.0 <= v <= 1.0 + 1e-6

    def test_save_timeline(self, mock_timeline, tmp_path):
        output = tmp_path / "timeline.json"
        save_timeline(mock_timeline, output)
        assert output.exists()
        loaded = json.loads(output.read_text())
        assert loaded["audio_file"] == "test.wav"
        assert loaded["summary"]["total_events"] == mock_timeline["summary"]["total_events"]


class TestJsonDefault:
    def test_numpy_float(self):
        assert _json_default(np.float64(1.5)) == 1.5

    def test_numpy_int(self):
        assert _json_default(np.int64(42)) == 42

    def test_numpy_array(self):
        assert _json_default(np.array([1, 2, 3])) == [1, 2, 3]

    def test_unsupported_type(self):
        with pytest.raises(TypeError):
            _json_default(set())
