"""
Tests for the full-song video generation pipeline (src/pipeline.py).

All external API calls (fal.ai, NAS SSH, Lexicon API) are mocked.
"""
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def brand_config():
    """Minimal brand config matching will_see.yaml structure."""
    return {
        "name": "Will See",
        "description": "8-bit lo-fi psychedelic nature",
        "lora_weights_url": "https://example.com/lora.safetensors",
        "style": {
            "base": "8-bit lo-fi pixel art style, retro video game aesthetic",
        },
        "sections": {
            "intro": {
                "prompt": "peaceful greenhouse interior, 8-bit pixel art",
                "motion": "slow gentle camera drift",
                "energy": "minimal",
            },
            "buildup": {
                "prompt": "plants beginning to glow and pulse, 8-bit pixel art",
                "motion": "gradually accelerating",
                "energy": "rising",
            },
            "drop": {
                "prompt": "explosive psychedelic greenhouse eruption, 8-bit pixel art",
                "motion": "explosive dynamic motion",
                "energy": "maximum intensity",
            },
            "breakdown": {
                "prompt": "calm aftermath, gentle bioluminescent glow, 8-bit pixel art",
                "motion": "slow floating drift",
                "energy": "calm",
            },
            "outro": {
                "prompt": "greenhouse at sunset, 8-bit pixel art",
                "motion": "very slow fade",
                "energy": "fading",
            },
        },
        "mood_modifiers": {
            "euphoric": {
                "colors": "vibrant neon greens",
                "atmosphere": "joyful nature explosion",
                "psychedelic": "kaleidoscopic plant fractals",
            },
        },
        "genre_modifiers": {
            "drum & bass": {
                "extra": "fast-growing jungle vines",
                "pixel_style": "chunky 8-bit pixels fragmenting",
            },
        },
        "output": {
            "resolution": "1920x1080",
            "fps": 30,
            "codec": "dxv",
        },
    }


@pytest.fixture
def sample_track():
    """Minimal Lexicon track dict."""
    return {
        "id": 42,
        "title": "Nan Slapper (Original Mix)",
        "artist": "Test Artist",
        "bpm": 87.5,
        "genre": "Drum & Bass",
        "key": "Am",
        "energy": 8,
        "happiness": 4,
        "duration": 300.0,
        "location": "/Volumes/Macintosh HD/Users/willcurran/SynologyDrive/Database/Test/track.flac",
    }


@pytest.fixture
def sample_analysis():
    """Minimal analysis dict from analyze_track."""
    return {
        "file_path": "/tmp/audio.flac",
        "title": "Nan Slapper (Original Mix)",
        "duration": 300.0,
        "bpm": 175.0,
        "time_signature": 4,
        "beats": [],
        "phrases": [
            {"start": 0.0, "end": 32.0, "beats": 16, "energy": 0.2,
             "spectral_centroid": 1000, "label": "intro"},
            {"start": 32.0, "end": 64.0, "beats": 16, "energy": 0.5,
             "spectral_centroid": 2000, "label": "buildup"},
            {"start": 64.0, "end": 128.0, "beats": 32, "energy": 0.9,
             "spectral_centroid": 4000, "label": "drop"},
            {"start": 128.0, "end": 192.0, "beats": 32, "energy": 0.3,
             "spectral_centroid": 1500, "label": "breakdown"},
            {"start": 192.0, "end": 256.0, "beats": 32, "energy": 0.85,
             "spectral_centroid": 3800, "label": "drop"},
            {"start": 256.0, "end": 300.0, "beats": 22, "energy": 0.15,
             "spectral_centroid": 800, "label": "outro"},
        ],
        "energy_envelope": [],
        "key": "Am",
        "genre_hint": "Drum & Bass",
        "mood": {
            "dominant_mood": "aggressive",
            "quadrant": "tense",
            "mood_descriptor": "intense dark energy",
            "valence": 0.3,
            "arousal": 0.8,
        },
    }


# ---------------------------------------------------------------------------
# Tests: _load_brand_config
# ---------------------------------------------------------------------------


class TestLoadBrandConfig:
    def test_loads_will_see_yaml(self):
        from src.pipeline import _load_brand_config
        config = _load_brand_config("will_see")
        assert config["name"] == "Will See"
        assert "sections" in config
        assert "drop" in config["sections"]

    def test_missing_brand_raises(self):
        from src.pipeline import _load_brand_config
        with pytest.raises(FileNotFoundError, match="Brand config not found"):
            _load_brand_config("nonexistent_brand_xyz")


class TestLoadLoraUrl:
    def test_loads_will_see_lora(self):
        from src.pipeline import _load_lora_url
        url = _load_lora_url("will_see")
        assert url.startswith("https://")
        assert "safetensors" in url

    def test_missing_lora_returns_empty(self):
        from src.pipeline import _load_lora_url
        url = _load_lora_url("nonexistent_brand_xyz")
        assert url == ""


# ---------------------------------------------------------------------------
# Tests: FullSongPipeline initialization
# ---------------------------------------------------------------------------


class TestPipelineInit:
    def test_parses_output_spec(self, brand_config):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        assert p.width == 1920
        assert p.height == 1080
        assert p.fps == 30
        assert p.codec == "dxv"
        assert p.lora_url == "https://example.com/lora.safetensors"

    def test_defaults_without_output_spec(self):
        from src.pipeline import FullSongPipeline
        config = {"name": "Test"}
        p = FullSongPipeline(config, fal_key="test", openai_key="test")
        assert p.width == 1920
        assert p.height == 1080
        assert p.fps == 30


# ---------------------------------------------------------------------------
# Tests: _plan_segments
# ---------------------------------------------------------------------------


class TestPlanSegments:
    def test_maps_all_phrase_labels(self, brand_config, sample_analysis):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        segments = p._plan_segments(sample_analysis)

        labels = [s["label"] for s in segments]
        assert "intro" in labels
        assert "buildup" in labels
        assert "drop" in labels
        assert "breakdown" in labels
        assert "outro" in labels

    def test_segments_cover_full_duration(self, brand_config, sample_analysis):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        segments = p._plan_segments(sample_analysis)

        assert segments[0]["start"] == 0.0
        assert segments[-1]["end"] == 300.0

        # No gaps between segments
        for i in range(1, len(segments)):
            assert segments[i]["start"] == segments[i - 1]["end"]

    def test_prompts_include_brand_section_text(self, brand_config, sample_analysis):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        segments = p._plan_segments(sample_analysis)

        # Find intro segment
        intro = [s for s in segments if s["label"] == "intro"][0]
        assert "greenhouse" in intro["prompt"].lower()

        # Find drop segment
        drop = [s for s in segments if s["label"] == "drop"][0]
        assert "explosive" in drop["prompt"].lower()

    def test_genre_modifier_applied(self, brand_config, sample_analysis):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        segments = p._plan_segments(sample_analysis)

        # DnB genre modifier should be in prompts
        drop = [s for s in segments if s["label"] == "drop"][0]
        assert "jungle vines" in drop["prompt"].lower()

    def test_style_override_included(self, brand_config, sample_analysis):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        segments = p._plan_segments(sample_analysis, style_override="dark tunnel aesthetic")

        for seg in segments:
            assert "dark tunnel aesthetic" in seg["prompt"]

    def test_fallback_single_segment_without_phrases(self, brand_config):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        analysis = {"duration": 120.0, "phrases": [], "mood": {}, "genre_hint": ""}
        segments = p._plan_segments(analysis)

        assert len(segments) == 1
        assert segments[0]["duration"] == 120.0
        assert segments[0]["label"] == "drop"

    def test_motion_prompt_present(self, brand_config, sample_analysis):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        segments = p._plan_segments(sample_analysis)

        for seg in segments:
            assert "motion_prompt" in seg
            assert len(seg["motion_prompt"]) > 0


# ---------------------------------------------------------------------------
# Tests: _map_label_to_section
# ---------------------------------------------------------------------------


class TestMapLabel:
    def test_standard_labels(self, brand_config):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        assert p._map_label_to_section("intro") == "intro"
        assert p._map_label_to_section("buildup") == "buildup"
        assert p._map_label_to_section("drop") == "drop"
        assert p._map_label_to_section("breakdown") == "breakdown"
        assert p._map_label_to_section("outro") == "outro"

    def test_aliases(self, brand_config):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        assert p._map_label_to_section("chorus") == "drop"
        assert p._map_label_to_section("peak") == "drop"
        assert p._map_label_to_section("bridge") == "breakdown"
        assert p._map_label_to_section("build") == "buildup"
        assert p._map_label_to_section("fade") == "outro"

    def test_unknown_defaults_to_buildup(self, brand_config):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        assert p._map_label_to_section("unknown_section") == "buildup"


# ---------------------------------------------------------------------------
# Tests: _build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_combines_all_parts(self, brand_config):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        result = p._build_prompt(
            section_prompt="base section prompt",
            mood_colors="neon green",
            mood_atmosphere="joyful",
            genre_extra="fast vines",
            genre_pixel="chunky pixels",
            style_override="tunnel style",
        )
        assert "base section prompt" in result
        assert "neon green" in result
        assert "joyful" in result
        assert "fast vines" in result
        assert "chunky pixels" in result
        assert "tunnel style" in result

    def test_skips_empty_parts(self, brand_config):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        result = p._build_prompt("base prompt", "", "", "", "", "")
        assert result == "base prompt"
        assert ",," not in result


# ---------------------------------------------------------------------------
# Tests: _generate_keyframe (mocked fal.ai)
# ---------------------------------------------------------------------------


class TestGenerateKeyframe:
    @mock.patch("src.pipeline.httpx.Client")
    def test_calls_fal_flux_lora(self, mock_httpx_client, brand_config, tmp_path):
        from src.pipeline import FullSongPipeline

        # Mock fal_client
        mock_fal = mock.MagicMock()
        mock_handle = mock.MagicMock()
        mock_handle.get.return_value = {
            "images": [{"url": "https://fal.ai/fake/image.png"}]
        }
        mock_fal.submit.return_value = mock_handle

        # Mock httpx download
        mock_response = mock.MagicMock()
        mock_response.content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        mock_response.raise_for_status = mock.MagicMock()
        mock_ctx = mock.MagicMock()
        mock_ctx.__enter__ = mock.MagicMock(return_value=mock.MagicMock(get=mock.MagicMock(return_value=mock_response)))
        mock_ctx.__exit__ = mock.MagicMock(return_value=False)
        mock_httpx_client.return_value = mock_ctx

        p = FullSongPipeline(brand_config, fal_key="test_key", openai_key="test")

        with mock.patch.dict("sys.modules", {"fal_client": mock_fal}):
            output = p._generate_keyframe(
                prompt="test prompt",
                lora_url="https://example.com/lora.safetensors",
                output_path=tmp_path / "keyframe.png",
            )

        # Verify fal_client.submit was called with flux-lora model
        mock_fal.submit.assert_called_once()
        call_args = mock_fal.submit.call_args
        assert call_args[0][0] == "fal-ai/flux-lora"

        # Verify LoRA was included
        arguments = call_args[1]["arguments"]
        assert "loras" in arguments
        assert arguments["loras"][0]["path"] == "https://example.com/lora.safetensors"

    def test_raises_without_fal_key(self, brand_config, tmp_path):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="", openai_key="test")

        with pytest.raises(ValueError, match="FAL_KEY required"):
            p._generate_keyframe(
                prompt="test",
                lora_url="",
                output_path=tmp_path / "kf.png",
            )


# ---------------------------------------------------------------------------
# Tests: _animate_segment (mocked fal.ai)
# ---------------------------------------------------------------------------


class TestAnimateSegment:
    def test_raises_without_fal_key(self, brand_config, tmp_path):
        from src.pipeline import FullSongPipeline
        p = FullSongPipeline(brand_config, fal_key="", openai_key="test")

        with pytest.raises(ValueError, match="FAL_KEY required"):
            p._animate_segment(
                keyframe=tmp_path / "kf.png",
                prompt="test motion",
                duration=5.0,
                output_path=tmp_path / "seg.mp4",
            )


# ---------------------------------------------------------------------------
# Tests: generate_for_track (integration, heavily mocked)
# ---------------------------------------------------------------------------


class TestGenerateForTrack:
    @mock.patch("src.pipeline.encode_for_resolume")
    @mock.patch("src.pipeline.stitch_videos")
    @mock.patch("src.pipeline.extract_frame")
    @mock.patch("src.pipeline.get_video_info")
    @mock.patch("src.pipeline.copy_from_nas")
    def test_dry_run_returns_segments(
        self, mock_copy, mock_info, mock_extract,
        mock_stitch, mock_encode,
        brand_config, sample_track, sample_analysis, tmp_path,
    ):
        from src.pipeline import FullSongPipeline
        from src.nas import NASManager

        mock_nas = mock.MagicMock(spec=NASManager)
        mock_nas.track_has_video.return_value = False
        mock_nas.get_nas_video_path.return_value = "/volume1/vj-content/Nan Slapper (Original Mix)/Nan Slapper (Original Mix).mov"

        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test", nas_manager=mock_nas)

        # Mock the analysis step
        with mock.patch.object(p, "_analyze_audio", return_value=sample_analysis):
            result = p.generate_for_track(
                track=sample_track,
                output_dir=tmp_path,
                dry_run=True,
            )

        assert result["dry_run"] is True
        assert result["title"] == "Nan Slapper (Original Mix)"
        assert result["bpm"] == 175.0  # Should be doubled from 87.5 for DnB
        assert len(result["segments"]) == 6

        # Should NOT have called any generation/encoding
        mock_copy.assert_called_once()  # Audio copy still happens
        mock_encode.assert_not_called()
        mock_nas.push_video.assert_not_called()

    def test_skips_existing_on_nas(self, brand_config, sample_track, tmp_path):
        from src.pipeline import FullSongPipeline
        from src.nas import NASManager

        mock_nas = mock.MagicMock(spec=NASManager)
        mock_nas.track_has_video.return_value = True
        mock_nas.get_nas_video_path.return_value = "/volume1/vj-content/Nan Slapper (Original Mix)/Nan Slapper (Original Mix).mov"
        mock_nas.get_track_video_path.return_value = "/Volumes/vj-content/Nan Slapper (Original Mix)/Nan Slapper (Original Mix).mov"

        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test", nas_manager=mock_nas)
        result = p.generate_for_track(track=sample_track, output_dir=tmp_path)

        assert result["skipped"] is True
        assert "nas_path" in result

    @mock.patch("src.pipeline.encode_for_resolume")
    @mock.patch("src.pipeline.stitch_videos")
    @mock.patch("src.pipeline.extract_frame")
    @mock.patch("src.pipeline.get_video_info", return_value={"duration": 8.0})
    @mock.patch("src.pipeline.copy_from_nas")
    def test_full_pipeline_metadata(
        self, mock_copy, mock_info, mock_extract,
        mock_stitch, mock_encode,
        brand_config, sample_track, sample_analysis, tmp_path,
    ):
        from src.pipeline import FullSongPipeline
        from src.nas import NASManager

        mock_nas = mock.MagicMock(spec=NASManager)
        # First call: pipeline checks if track already exists (False)
        # Second call: auto_rebuild_show checks if track has video (True)
        mock_nas.track_has_video.side_effect = [False, True]
        mock_nas.get_nas_video_path.return_value = "/volume1/vj-content/Nan Slapper (Original Mix)/Nan Slapper (Original Mix).mov"
        mock_nas.get_track_video_path.return_value = "/Volumes/vj-content/Nan Slapper (Original Mix)/Nan Slapper (Original Mix).mov"
        # Mock for auto_rebuild_show (called at end of pipeline)
        mock_nas.list_tracks.return_value = ["Nan Slapper (Original Mix)"]
        mock_nas.pull_metadata.return_value = {"artist": "Test Artist", "bpm": 175.0, "duration": 300.0}

        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test", nas_manager=mock_nas)

        # Mock internal methods that call external APIs
        mock_kf = tmp_path / "fake_keyframe.png"
        mock_kf.write_bytes(b"\x89PNG" + b"\x00" * 100)

        mock_vid = tmp_path / "fake_segment.mp4"
        mock_vid.write_bytes(b"\x00" * 1000)

        with mock.patch.object(p, "_analyze_audio", return_value=sample_analysis), \
             mock.patch.object(p, "_generate_keyframe", return_value=mock_kf), \
             mock.patch.object(p, "_animate_segment", return_value=mock_vid):

            result = p.generate_for_track(
                track=sample_track,
                output_dir=tmp_path,
            )

        assert result["title"] == "Nan Slapper (Original Mix)"
        assert result["artist"] == "Test Artist"
        assert result["brand"] == "Will See"
        assert "nas_path" in result
        assert "local_vj_path" in result
        assert result["segments"] == 6
        assert "generated_at" in result

        # Verify NAS push was called
        mock_nas.push_video.assert_called_once()
        mock_nas.push_metadata.assert_called_once()
        mock_nas.register_track.assert_called_once()

        # Verify auto-rebuild was triggered (push_show called)
        mock_nas.push_show.assert_called_once()

        # Verify metadata file was written
        track_dirname = "nan_slapper_original_mix"
        meta_path = tmp_path / track_dirname / "track_metadata.json"
        assert meta_path.exists()
        meta = json.loads(meta_path.read_text())
        assert meta["title"] == "Nan Slapper (Original Mix)"


# ---------------------------------------------------------------------------
# Tests: _stitch_and_encode convenience method
# ---------------------------------------------------------------------------


class TestStitchAndEncode:
    @mock.patch("src.pipeline.encode_for_resolume")
    @mock.patch("src.pipeline.stitch_videos")
    def test_calls_stitch_then_encode(self, mock_stitch, mock_encode, brand_config, tmp_path):
        from src.pipeline import FullSongPipeline

        p = FullSongPipeline(brand_config, fal_key="test", openai_key="test")
        segs = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        output = tmp_path / "final.mov"

        p._stitch_and_encode(segs, target_duration=60.0, output=output)

        mock_stitch.assert_called_once()
        mock_encode.assert_called_once()
        # Verify encode uses DXV codec from brand config
        encode_call = mock_encode.call_args
        assert encode_call[1]["codec"] == "dxv"
        assert encode_call[1]["fps"] == 30
