"""
Integration tests that exercise multiple modules together WITHOUT API keys.

These tests use synthetic audio and mock external services to validate
the interaction between analysis, pipeline, NAS, and show-building modules.
"""
import json
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import soundfile as sf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_synthetic_audio(
    bpm: float = 128.0, duration: float = 30.0, sr: int = 22050,
) -> str:
    """Create a synthetic audio file with beat pattern and energy variation."""
    n = int(duration * sr)
    y = np.zeros(n)
    beat_samples = int(60.0 / bpm * sr)
    click_len = int(0.005 * sr)

    for i in range(0, n, beat_samples):
        beat_num = i // beat_samples
        amp = 0.9 if beat_num % 4 == 0 else 0.5
        end = min(i + click_len, n)
        y[i:end] = amp * np.sin(2 * np.pi * 800 * np.arange(end - i) / sr)

    # Energy curve: low -> buildup -> drop -> breakdown -> drop -> outro
    sections = [
        (0.0, 0.2, 0.2),
        (0.2, 0.35, 0.5),
        (0.35, 0.55, 0.9),
        (0.55, 0.7, 0.3),
        (0.7, 0.9, 0.95),
        (0.9, 1.0, 0.15),
    ]
    for start_frac, end_frac, energy in sections:
        s = int(start_frac * n)
        e = int(end_frac * n)
        t = np.arange(e - s) / sr
        y[s:e] += energy * 0.3 * (
            np.sin(2 * np.pi * 100 * t) +
            0.5 * np.sin(2 * np.pi * 200 * t) +
            0.3 * np.random.randn(e - s) * energy
        )

    y = np.clip(y, -1.0, 1.0)
    path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    sf.write(path, y, sr)
    return path


# ---------------------------------------------------------------------------
# Integration: Audio analysis pipeline
# ---------------------------------------------------------------------------

class TestAnalysisPipeline:
    """Test the full analysis chain: audio -> phrases -> mood-compatible dict."""

    def test_analyze_synthetic_audio(self):
        """analyze_track produces valid structured output."""
        from src.analyzer.audio import analyze_track

        audio_path = _make_synthetic_audio(bpm=128.0, duration=30.0)
        analysis = analyze_track(audio_path)

        assert analysis.bpm > 0
        assert analysis.duration > 0
        assert len(analysis.beats) > 0
        assert len(analysis.phrases) >= 2

    def test_analysis_dict_has_required_fields(self):
        """to_dict() output has all fields needed by the pipeline."""
        from src.analyzer.audio import analyze_track

        audio_path = _make_synthetic_audio(bpm=128.0, duration=30.0)
        analysis = analyze_track(audio_path)
        d = analysis.to_dict()

        assert "bpm" in d
        assert "duration" in d
        assert "phrases" in d
        assert "beats" in d
        assert "energy_envelope" in d
        assert isinstance(d["phrases"], list)

    def test_analysis_phrases_have_labels(self):
        """Each phrase should have a label for pipeline segment mapping."""
        from src.analyzer.audio import analyze_track

        audio_path = _make_synthetic_audio(bpm=128.0, duration=30.0)
        analysis = analyze_track(audio_path)

        for phrase in analysis.phrases:
            assert phrase.label != ""
            assert phrase.start < phrase.end
            assert phrase.beats > 0

    def test_bpm_override_respected(self):
        """BPM override should be used instead of detected BPM."""
        from src.analyzer.audio import analyze_track

        audio_path = _make_synthetic_audio(bpm=128.0, duration=10.0)
        analysis = analyze_track(audio_path, bpm_override=175.0)

        assert abs(analysis.bpm - 175.0) < 1.0

    def test_analysis_serializes_to_json(self):
        """Analysis output should be JSON-serializable."""
        from src.analyzer.audio import analyze_track

        audio_path = _make_synthetic_audio(bpm=128.0, duration=10.0)
        analysis = analyze_track(audio_path)
        json_str = analysis.to_json()

        data = json.loads(json_str)
        assert data["bpm"] > 0
        assert len(data["phrases"]) > 0


# ---------------------------------------------------------------------------
# Integration: NAS path mapping
# ---------------------------------------------------------------------------

class TestNASPathMapping:
    """Test NASManager path translation between NAS and Resolume mount."""

    def test_nas_to_resolume_path(self):
        from src.nas import NASManager

        nas = NASManager()
        nas_path = nas.get_nas_video_path("My Track (Extended Mix)")
        resolume_path = nas.get_track_video_path("My Track (Extended Mix)")

        assert "/volume1/vj-content/" in nas_path
        assert "/Volumes/vj-content/" in resolume_path
        assert nas_path.endswith(".mov")
        assert resolume_path.endswith(".mov")
        # Both should contain the track title
        assert "My Track (Extended Mix)" in nas_path
        assert "My Track (Extended Mix)" in resolume_path

    def test_custom_mount_point(self):
        from src.nas import NASManager

        nas = NASManager(
            base_path="/data/vj",
            resolume_mount="/Volumes/custom",
        )
        path = nas.get_track_video_path("Song")
        assert path.startswith("/Volumes/custom/")
        assert path.endswith("Song.mov")

        nas_path = nas.get_nas_video_path("Song")
        assert nas_path.startswith("/data/vj/")
        assert nas_path.endswith("Song.mov")

    def test_path_with_special_characters(self):
        from src.nas import NASManager

        nas = NASManager()
        title = "Track (feat. DJ & MC) [Extended Mix]"
        path = nas.get_track_video_path(title)
        assert title in path
        assert path.endswith(".mov")

    def test_empty_mount_returns_nas_path(self):
        from src.nas import NASManager

        nas = NASManager()
        path = nas.get_track_video_path("Track", as_resolume_mount="")
        assert "/volume1/vj-content/" in path

    def test_different_extensions(self):
        from src.nas import NASManager

        nas = NASManager()
        mov_path = nas.get_track_video_path("Song", extension=".mov")
        mp4_path = nas.get_track_video_path("Song", extension=".mp4")
        assert mov_path.endswith(".mov")
        assert mp4_path.endswith(".mp4")

    @mock.patch("subprocess.run")
    def test_list_tracks_filters_system_dirs(self, mock_run):
        from src.nas import NASManager

        mock_run.return_value = mock.MagicMock(
            returncode=0,
            stdout=b"Track A\nTrack B\n.DS_Store\n.rsv\n",
            stderr=b"",
        )
        nas = NASManager()
        tracks = nas.list_tracks()
        assert tracks == ["Track A", "Track B"]

    @mock.patch("subprocess.run")
    def test_track_has_video_mocked(self, mock_run):
        from src.nas import NASManager

        mock_run.return_value = mock.MagicMock(
            returncode=0, stdout=b"EXISTS", stderr=b"",
        )
        nas = NASManager()
        assert nas.track_has_video("Test Track") is True


# ---------------------------------------------------------------------------
# Integration: Show composition builder
# ---------------------------------------------------------------------------

class TestShowCompositionBuilder:
    """Test building .avc compositions from track metadata."""

    def test_build_show_from_tracks(self):
        import xml.etree.ElementTree as ET
        from src.resolume.show import build_production_show

        tracks = [
            {
                "title": "Track A (Original Mix)",
                "artist": "Artist A",
                "video_path": "/Volumes/vj-content/Track A/Track A.mov",
                "bpm": 128.0,
                "duration": 360.0,
            },
            {
                "title": "Track B (Extended Mix)",
                "artist": "Artist B",
                "video_path": "/Volumes/vj-content/Track B/Track B.mov",
                "bpm": 130.0,
                "duration": 420.0,
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "Test Show.avc"
            result = build_production_show(tracks, avc_path, show_name="Test Show")

            assert result["track_count"] == 2
            assert result["show_name"] == "Test Show"
            assert avc_path.exists()

            # Verify XML is parseable
            content = avc_path.read_text()
            # Strip XML declaration if present
            xml_body = content.split("\n", 1)[1] if content.startswith("<?xml") else content
            root = ET.fromstring(xml_body)
            assert root.tag == "Composition"
            assert root.get("name") == "Test Show"

    def test_build_show_creates_manifest(self):
        from src.resolume.show import build_production_show

        tracks = [
            {
                "title": "Solo Track",
                "artist": "Test",
                "video_path": "/path/to/video.mov",
                "bpm": 125.0,
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "Show.avc"
            result = build_production_show(tracks, avc_path)

            manifest_path = Path(result["manifest_path"])
            assert manifest_path.exists()

            manifest = json.loads(manifest_path.read_text())
            assert manifest["track_count"] == 1
            assert manifest["tracks"][0]["title"] == "Solo Track"

    def test_add_track_to_existing_show(self):
        from src.resolume.show import build_production_show, add_track_to_show

        initial_tracks = [
            {"title": "Track 1", "video_path": "/path/1.mov", "bpm": 128.0},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "Show.avc"
            result1 = build_production_show(initial_tracks, avc_path)

            new_track = {
                "title": "Track 2",
                "artist": "New Artist",
                "video_path": "/path/2.mov",
                "bpm": 130.0,
            }
            result2 = add_track_to_show(new_track, Path(result1["manifest_path"]))
            assert result2["track_count"] == 2

    def test_rebuild_from_output_directory(self):
        from src.resolume.show import rebuild_show_from_output_dir

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            # Create track directories with metadata
            for i, title in enumerate(["Song A", "Song B"]):
                track_dir = base / f"track_{i}"
                track_dir.mkdir()
                meta = {
                    "title": title,
                    "artist": f"Artist {i}",
                    "local_vj_path": f"/Volumes/vj-content/{title}/{title}.mov",
                    "bpm": 128.0 + i * 2,
                }
                (track_dir / "track_metadata.json").write_text(json.dumps(meta))

            avc_path = base / "Rebuilt.avc"
            result = rebuild_show_from_output_dir(base, avc_path)
            assert result["track_count"] == 2
            assert avc_path.exists()


# ---------------------------------------------------------------------------
# Integration: Brand guide loading
# ---------------------------------------------------------------------------

class TestBrandGuideLoading:
    """Test loading and using brand configuration YAML."""

    def test_load_example_brand(self):
        from src.pipeline import _load_brand_config

        config = _load_brand_config("example")
        assert config["name"] == "Example Brand"
        assert "sections" in config
        assert "style" in config
        assert "mood_modifiers" in config
        assert "genre_modifiers" in config
        assert "output" in config

    def test_brand_sections_complete(self):
        from src.pipeline import _load_brand_config

        config = _load_brand_config("example")
        expected_sections = {"intro", "buildup", "drop", "breakdown", "outro"}
        assert set(config["sections"].keys()) == expected_sections

        for section_name, section in config["sections"].items():
            assert "prompt" in section, f"Section {section_name} missing prompt"
            assert "motion" in section, f"Section {section_name} missing motion"
            assert "energy" in section, f"Section {section_name} missing energy"

    def test_brand_output_spec(self):
        from src.pipeline import _load_brand_config

        config = _load_brand_config("example")
        output = config["output"]
        assert output["resolution"] == "1920x1080"
        assert output["fps"] == 30
        assert output["codec"] == "dxv"

    def test_missing_brand_raises(self):
        from src.pipeline import _load_brand_config

        with pytest.raises(FileNotFoundError, match="Brand config not found"):
            _load_brand_config("nonexistent_brand_xyz")

    def test_brand_lora_url(self):
        from src.pipeline import _load_lora_url

        url = _load_lora_url("example")
        assert url.startswith("https://")
        assert "safetensors" in url


# ---------------------------------------------------------------------------
# Integration: Pipeline segment planning (no API keys needed)
# ---------------------------------------------------------------------------

class TestPipelineSegmentPlanning:
    """Test pipeline segment planning using brand config + analysis data."""

    def test_plan_segments_from_analysis(self):
        from src.pipeline import FullSongPipeline, _load_brand_config

        config = _load_brand_config("example")
        pipeline = FullSongPipeline(config, fal_key="test", openai_key="test")

        analysis = {
            "duration": 120.0,
            "phrases": [
                {"start": 0.0, "end": 30.0, "beats": 16, "energy": 0.2,
                 "spectral_centroid": 1000, "label": "intro"},
                {"start": 30.0, "end": 60.0, "beats": 16, "energy": 0.6,
                 "spectral_centroid": 2000, "label": "buildup"},
                {"start": 60.0, "end": 90.0, "beats": 16, "energy": 0.9,
                 "spectral_centroid": 3500, "label": "drop"},
                {"start": 90.0, "end": 120.0, "beats": 16, "energy": 0.2,
                 "spectral_centroid": 900, "label": "outro"},
            ],
            "mood": {"quadrant": "euphoric", "mood_descriptor": "uplifting"},
            "genre_hint": "drum & bass",
        }

        segments = pipeline._plan_segments(analysis)

        # 30s phrases split at beat-quantized intervals (8 beats = 3.75s at 128 BPM)
        assert len(segments) > 4  # Each 30s phrase splits into multiple segments
        assert segments[0]["label"] == "intro"
        assert segments[-1]["label"] == "outro"

        # Segments should cover full duration
        assert segments[0]["start"] == 0.0
        assert segments[-1]["end"] == 120.0

        # Each segment should have prompt and motion_prompt
        for seg in segments:
            assert "prompt" in seg
            assert "motion_prompt" in seg
            assert len(seg["prompt"]) > 20

    def test_segments_include_genre_modifiers(self):
        from src.pipeline import FullSongPipeline, _load_brand_config

        config = _load_brand_config("example")
        pipeline = FullSongPipeline(config, fal_key="test", openai_key="test")

        analysis = {
            "duration": 30.0,
            "phrases": [
                {"start": 0.0, "end": 30.0, "beats": 16, "energy": 0.9,
                 "spectral_centroid": 3000, "label": "drop"},
            ],
            "mood": {},
            "genre_hint": "drum & bass",
        }

        segments = pipeline._plan_segments(analysis)
        # Example brand has genre modifier for "drum & bass" with "jungle vines"
        assert "jungle vines" in segments[0]["prompt"].lower() or \
               "vine" in segments[0]["prompt"].lower()

    def test_dry_run_skips_generation(self):
        """Dry run should return segment plan without calling external APIs."""
        from src.pipeline import FullSongPipeline, _load_brand_config
        from src.nas import NASManager

        config = _load_brand_config("example")

        mock_nas = mock.MagicMock(spec=NASManager)
        mock_nas.base_path = "/volume1/vj-content"
        mock_nas.resolume_mount = "/Volumes/vj-content"
        mock_nas.track_has_video.return_value = False

        pipeline = FullSongPipeline(
            config, fal_key="test", openai_key="test", nas_manager=mock_nas
        )

        track = {
            "title": "Test Track",
            "artist": "Test Artist",
            "bpm": 128.0,
            "location": "/some/path/track.flac",
        }

        sample_analysis = {
            "duration": 60.0,
            "phrases": [
                {"start": 0.0, "end": 30.0, "beats": 16, "energy": 0.5,
                 "spectral_centroid": 2000, "label": "buildup"},
                {"start": 30.0, "end": 60.0, "beats": 16, "energy": 0.9,
                 "spectral_centroid": 3500, "label": "drop"},
            ],
            "mood": {},
            "genre_hint": "",
        }

        with mock.patch("src.pipeline.copy_from_nas"), \
             mock.patch.object(pipeline, "_analyze_audio", return_value=sample_analysis):
            result = pipeline.generate_for_track(
                track=track,
                output_dir=Path(tempfile.mkdtemp()),
                dry_run=True,
            )

        assert result["dry_run"] is True
        # 30s phrases split at beat-quantized intervals
        assert len(result["segments"]) >= 2
        assert result["title"] == "Test Track"


# ---------------------------------------------------------------------------
# Integration: Analysis + sonic mapper
# ---------------------------------------------------------------------------

class TestAnalysisWithSonicMapper:
    """Test that sonic mapper works with analysis-style segment data."""

    def test_sonic_profiles_from_segments(self):
        from src.analyzer.sonic_mapper import create_segment_sonic_profiles

        # Simulate a timeline with events
        timeline = {
            "events": [
                {"time": 5.0, "stem": "bass", "event_type": "drop",
                 "spectral_character": "clean", "intensity": 0.9},
                {"time": 15.0, "stem": "drums", "event_type": "stab",
                 "spectral_character": "clean", "intensity": 0.7},
            ],
            "per_frame_data": {
                "fps": 30,
                "total_frames": 600,
                "stems": {
                    "drums": {"energy": [0.5] * 600},
                    "bass": {"energy": [0.6] * 600},
                    "other": {"energy": [0.3] * 600},
                    "vocals": {"energy": [0.1] * 600},
                },
            },
        }

        segments = [
            {"start": 0.0, "end": 10.0, "label": "intro"},
            {"start": 10.0, "end": 20.0, "label": "drop"},
        ]

        profiles = create_segment_sonic_profiles(timeline, segments)
        assert len(profiles) == 2
        assert profiles[0].has_bass_drop is True  # Event at 5.0s
        assert profiles[1].has_bass_drop is False

    def test_enhanced_prompts_include_sonic_data(self):
        from src.analyzer.sonic_mapper import (
            SegmentSonicProfile, enhance_segment_prompt,
        )

        profile = SegmentSonicProfile(
            start_time=0, end_time=10, duration=10,
            sonic_prompt="massive bass drop, heavy percussion",
            eye_prompt="eyes snap open",
            has_bass_drop=True,
            drums_energy=0.7,
        )

        enhanced = enhance_segment_prompt(
            "peaceful pixel art greenhouse", profile, include_eyes=True,
        )
        assert "peaceful pixel art greenhouse" in enhanced
        assert "massive bass drop" in enhanced
        assert "eyes snap open" in enhanced
