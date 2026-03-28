"""Tests for the full-song video generation pipeline.

All tests run offline -- API calls are mocked, no keys needed.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.generator.video_pipeline import (
    SUPPORTED_VIDEO_MODELS,
    VideoGenerationConfig,
    _concat_segments,
    _extract_last_frame,
    _get_video_duration,
    _plan_segments,
    _reencode_video,
    _stitch_segments,
    build_keyframe_prompt,
    build_segment_prompt,
    estimate_cost,
    generate_full_song_video,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_analysis():
    """Minimal TrackAnalysis.to_dict() output for testing."""
    return {
        "file_path": "/tmp/test_song.flac",
        "title": "Test Song",
        "duration": 180.0,
        "bpm": 128.0,
        "time_signature": 4,
        "phrases": [
            {
                "start": 0.0,
                "end": 30.0,
                "beats": 64,
                "energy": 0.3,
                "spectral_centroid": 2000.0,
                "label": "intro",
            },
            {
                "start": 30.0,
                "end": 60.0,
                "beats": 64,
                "energy": 0.6,
                "spectral_centroid": 3500.0,
                "label": "buildup",
            },
            {
                "start": 60.0,
                "end": 90.0,
                "beats": 64,
                "energy": 0.9,
                "spectral_centroid": 5000.0,
                "label": "drop",
            },
            {
                "start": 90.0,
                "end": 120.0,
                "beats": 64,
                "energy": 0.4,
                "spectral_centroid": 2500.0,
                "label": "breakdown",
            },
            {
                "start": 120.0,
                "end": 150.0,
                "beats": 64,
                "energy": 0.85,
                "spectral_centroid": 4800.0,
                "label": "drop",
            },
            {
                "start": 150.0,
                "end": 180.0,
                "beats": 64,
                "energy": 0.25,
                "spectral_centroid": 1800.0,
                "label": "outro",
            },
        ],
        "mood": {
            "happy": 0.7,
            "sad": 0.1,
            "aggressive": 0.3,
            "relaxed": 0.2,
            "party": 0.8,
            "valence": 0.72,
            "arousal": 0.68,
            "dominant_mood": "party",
            "quadrant": "euphoric",
            "mood_descriptor": "euphoric festival energy, high energy",
        },
        "beats": [],
        "energy_envelope": [],
    }


@pytest.fixture
def default_config():
    """Default VideoGenerationConfig for testing."""
    return VideoGenerationConfig(
        video_model="kling-v1",
        openai_key="test-openai-key",
        fal_key="test-fal-key",
        style_prompt="abstract neon geometry",
    )


@pytest.fixture
def tmp_dir():
    """Temporary directory, cleaned up after test."""
    d = tempfile.mkdtemp(prefix="rsv_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Model registry tests
# ---------------------------------------------------------------------------

class TestSupportedModels:
    """Test the SUPPORTED_VIDEO_MODELS registry."""

    def test_all_models_have_required_fields(self):
        required = {"provider", "model_id", "max_duration", "cost_per_sec", "supports_i2v"}
        for name, spec in SUPPORTED_VIDEO_MODELS.items():
            missing = required - set(spec.keys())
            assert not missing, f"Model '{name}' missing fields: {missing}"

    def test_at_least_five_models(self):
        assert len(SUPPORTED_VIDEO_MODELS) >= 5

    def test_known_models_present(self):
        assert "kling-v1" in SUPPORTED_VIDEO_MODELS
        assert "kling-v1-5" in SUPPORTED_VIDEO_MODELS
        assert "minimax" in SUPPORTED_VIDEO_MODELS
        assert "runway-gen3" in SUPPORTED_VIDEO_MODELS
        assert "wan2.1" in SUPPORTED_VIDEO_MODELS

    def test_all_support_image_to_video(self):
        for name, spec in SUPPORTED_VIDEO_MODELS.items():
            assert spec["supports_i2v"], f"Model '{name}' must support image-to-video"

    def test_providers_are_valid(self):
        for name, spec in SUPPORTED_VIDEO_MODELS.items():
            assert spec["provider"] in ("fal", "replicate"), (
                f"Model '{name}' has unknown provider: {spec['provider']}"
            )

    def test_max_durations_are_positive(self):
        for name, spec in SUPPORTED_VIDEO_MODELS.items():
            assert spec["max_duration"] > 0

    def test_costs_are_reasonable(self):
        for name, spec in SUPPORTED_VIDEO_MODELS.items():
            assert 0.01 <= spec["cost_per_sec"] <= 1.0, (
                f"Model '{name}' cost ${spec['cost_per_sec']}/s seems wrong"
            )


# ---------------------------------------------------------------------------
# Prompt engineering tests
# ---------------------------------------------------------------------------

class TestBuildSegmentPrompt:
    """Test build_segment_prompt() prompt engineering."""

    def test_includes_style_prompt(self):
        prompt = build_segment_prompt(
            mood_descriptor="euphoric",
            mood_quadrant="euphoric",
            phrase_label="drop",
            energy=0.8,
            style_prompt="neon fractals",
            segment_index=0,
            total_segments=5,
        )
        assert "neon fractals" in prompt

    def test_includes_mood_visuals(self):
        prompt = build_segment_prompt(
            mood_descriptor="",
            mood_quadrant="tense",
            phrase_label="drop",
            energy=0.8,
            style_prompt="",
            segment_index=0,
            total_segments=5,
        )
        assert "harsh shadows" in prompt or "deep reds" in prompt

    def test_includes_motion_guidance_for_drop(self):
        prompt = build_segment_prompt(
            mood_descriptor="",
            mood_quadrant="euphoric",
            phrase_label="drop",
            energy=0.9,
            style_prompt="",
            segment_index=0,
            total_segments=5,
        )
        assert "energetic" in prompt.lower()
        assert "dynamic" in prompt.lower()

    def test_includes_motion_guidance_for_breakdown(self):
        prompt = build_segment_prompt(
            mood_descriptor="",
            mood_quadrant="serene",
            phrase_label="breakdown",
            energy=0.3,
            style_prompt="",
            segment_index=0,
            total_segments=5,
        )
        assert "smooth" in prompt.lower()

    def test_includes_vj_baseline(self):
        prompt = build_segment_prompt(
            mood_descriptor="",
            mood_quadrant="euphoric",
            phrase_label="drop",
            energy=0.5,
            style_prompt="",
            segment_index=0,
            total_segments=1,
        )
        assert "volumetric lighting" in prompt
        assert "no text" in prompt
        assert "no watermarks" in prompt

    def test_high_energy_modifier(self):
        prompt = build_segment_prompt(
            mood_descriptor="",
            mood_quadrant="euphoric",
            phrase_label="drop",
            energy=0.9,
            style_prompt="",
            segment_index=0,
            total_segments=1,
        )
        assert "maximum intensity" in prompt

    def test_low_energy_modifier(self):
        prompt = build_segment_prompt(
            mood_descriptor="",
            mood_quadrant="melancholic",
            phrase_label="breakdown",
            energy=0.1,
            style_prompt="",
            segment_index=0,
            total_segments=1,
        )
        assert "minimal energy" in prompt

    def test_mood_descriptor_included(self):
        prompt = build_segment_prompt(
            mood_descriptor="euphoric festival energy",
            mood_quadrant="euphoric",
            phrase_label="drop",
            energy=0.8,
            style_prompt="",
            segment_index=0,
            total_segments=1,
        )
        assert "euphoric festival energy" in prompt

    def test_all_quadrants_produce_different_prompts(self):
        prompts = {}
        for quadrant in ("euphoric", "tense", "melancholic", "serene"):
            prompts[quadrant] = build_segment_prompt(
                mood_descriptor="",
                mood_quadrant=quadrant,
                phrase_label="drop",
                energy=0.5,
                style_prompt="",
                segment_index=0,
                total_segments=1,
            )
        # All should be unique
        values = list(prompts.values())
        assert len(set(values)) == 4


class TestBuildKeyframePrompt:
    """Test build_keyframe_prompt() for still image generation."""

    def test_includes_style(self):
        prompt = build_keyframe_prompt(
            mood_descriptor="",
            mood_quadrant="euphoric",
            phrase_label="drop",
            energy=0.8,
            style_prompt="cyberpunk city",
        )
        assert "cyberpunk city" in prompt

    def test_drop_has_bold_composition(self):
        prompt = build_keyframe_prompt(
            mood_descriptor="",
            mood_quadrant="euphoric",
            phrase_label="drop",
            energy=0.8,
            style_prompt="",
        )
        assert "bold" in prompt.lower() or "dramatic" in prompt.lower()

    def test_breakdown_has_spacious_composition(self):
        prompt = build_keyframe_prompt(
            mood_descriptor="",
            mood_quadrant="serene",
            phrase_label="breakdown",
            energy=0.3,
            style_prompt="",
        )
        assert "spacious" in prompt.lower() or "breathing" in prompt.lower()

    def test_no_faces_no_text(self):
        prompt = build_keyframe_prompt(
            mood_descriptor="",
            mood_quadrant="euphoric",
            phrase_label="drop",
            energy=0.5,
            style_prompt="",
        )
        assert "no text" in prompt
        assert "no human faces" in prompt


# ---------------------------------------------------------------------------
# Segment planning tests
# ---------------------------------------------------------------------------

class TestPlanSegments:
    """Test _plan_segments() song structure planning."""

    def test_one_segment_per_phrase_when_fits(self, sample_analysis):
        """Each phrase becomes one segment when within model max duration."""
        segments = _plan_segments(sample_analysis, max_segment_duration=60)
        assert len(segments) == 6  # 6 phrases

    def test_splits_long_phrases(self, sample_analysis):
        """Phrases longer than max_segment_duration get split."""
        segments = _plan_segments(sample_analysis, max_segment_duration=10)
        # Each 30s phrase should split into 3 segments of 10s
        assert len(segments) > 6

    def test_segment_indices_are_sequential(self, sample_analysis):
        segments = _plan_segments(sample_analysis, max_segment_duration=60)
        for i, seg in enumerate(segments):
            assert seg["segment_index"] == i

    def test_segments_cover_full_duration(self, sample_analysis):
        segments = _plan_segments(sample_analysis, max_segment_duration=60)
        assert segments[0]["start"] == 0.0
        assert segments[-1]["end"] == 180.0

    def test_no_gaps_between_segments(self, sample_analysis):
        segments = _plan_segments(sample_analysis, max_segment_duration=10)
        for i in range(1, len(segments)):
            assert segments[i]["start"] == pytest.approx(
                segments[i - 1]["end"], abs=0.01
            ), f"Gap between segment {i - 1} and {i}"

    def test_inherits_mood_from_analysis(self, sample_analysis):
        segments = _plan_segments(sample_analysis, max_segment_duration=60)
        for seg in segments:
            assert seg["mood_quadrant"] == "euphoric"
            assert "euphoric" in seg["mood_descriptor"]

    def test_preserves_phrase_labels(self, sample_analysis):
        segments = _plan_segments(sample_analysis, max_segment_duration=60)
        labels = [s["label"] for s in segments]
        assert labels == ["intro", "buildup", "drop", "breakdown", "drop", "outro"]

    def test_empty_phrases_fallback(self):
        analysis = {"phrases": [], "duration": 120.0, "mood": {}}
        segments = _plan_segments(analysis, max_segment_duration=10)
        assert len(segments) == 1
        assert segments[0]["duration"] == 120.0

    def test_very_short_chunks_absorbed(self, sample_analysis):
        """Chunks shorter than 1s should be absorbed into the previous segment."""
        # Create analysis with one phrase of 10.5s, max_segment=10
        analysis = {
            "phrases": [
                {"start": 0.0, "end": 10.5, "beats": 16, "energy": 0.5,
                 "spectral_centroid": 2000.0, "label": "drop"},
            ],
            "duration": 10.5,
            "mood": {"mood_descriptor": "test", "quadrant": "euphoric"},
        }
        segments = _plan_segments(analysis, max_segment_duration=10)
        # The 0.5s remainder should be absorbed into the first segment
        assert len(segments) == 1
        assert segments[0]["end"] == 10.5

    def test_segment_durations_positive(self, sample_analysis):
        segments = _plan_segments(sample_analysis, max_segment_duration=10)
        for seg in segments:
            assert seg["duration"] > 0


# ---------------------------------------------------------------------------
# Cost estimation tests
# ---------------------------------------------------------------------------

class TestEstimateCost:
    """Test estimate_cost() calculations."""

    def test_basic_cost_estimate(self):
        config = VideoGenerationConfig(video_model="kling-v1")
        cost = estimate_cost(180.0, config)
        assert cost["model"] == "kling-v1"
        assert cost["audio_duration_sec"] == 180.0
        assert cost["video_cost"] > 0
        assert cost["keyframe_cost"] > 0
        assert cost["total_cost"] == cost["video_cost"] + cost["keyframe_cost"]

    def test_cheaper_model_cheaper_cost(self):
        config_kling = VideoGenerationConfig(video_model="kling-v1")
        config_minimax = VideoGenerationConfig(video_model="minimax")
        cost_kling = estimate_cost(180.0, config_kling)
        cost_minimax = estimate_cost(180.0, config_minimax)
        assert cost_minimax["video_cost"] < cost_kling["video_cost"]

    def test_longer_audio_higher_cost(self):
        config = VideoGenerationConfig(video_model="kling-v1")
        cost_short = estimate_cost(60.0, config)
        cost_long = estimate_cost(300.0, config)
        assert cost_long["total_cost"] > cost_short["total_cost"]

    def test_unknown_model_returns_error(self):
        config = VideoGenerationConfig(video_model="nonexistent-model")
        cost = estimate_cost(60.0, config)
        assert "error" in cost

    def test_high_quality_keyframes_cost_more(self):
        config_high = VideoGenerationConfig(video_model="kling-v1", quality="high")
        config_draft = VideoGenerationConfig(video_model="kling-v1", quality="draft")
        cost_high = estimate_cost(180.0, config_high)
        cost_draft = estimate_cost(180.0, config_draft)
        assert cost_high["keyframe_cost"] > cost_draft["keyframe_cost"]

    def test_cost_breakdown_fields(self):
        config = VideoGenerationConfig(video_model="kling-v1")
        cost = estimate_cost(120.0, config)
        assert "num_segments" in cost
        assert "max_segment_duration" in cost
        assert "provider" in cost
        assert cost["provider"] == "fal"


# ---------------------------------------------------------------------------
# Keyframe generation tests (mocked API)
# ---------------------------------------------------------------------------

class TestGenerateKeyframe:
    """Test _generate_keyframe() with mocked OpenAI API."""

    def test_generates_keyframe_image(self, tmp_dir):
        from src.generator.video_pipeline import _generate_keyframe

        config = VideoGenerationConfig(openai_key="test-key")
        output = tmp_dir / "keyframe.png"

        fake_image_bytes = b"\x89PNG\r\n" + b"\x00" * 1000

        with patch("src.generator.video_pipeline.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)

            # First call: OpenAI images API
            mock_api_resp = MagicMock()
            mock_api_resp.json.return_value = {
                "data": [{"url": "https://example.com/image.png"}]
            }
            mock_api_resp.raise_for_status = MagicMock()

            # Second call: download image
            mock_dl_resp = MagicMock()
            mock_dl_resp.content = fake_image_bytes
            mock_dl_resp.raise_for_status = MagicMock()

            mock_client.post.return_value = mock_api_resp
            mock_client.get.return_value = mock_dl_resp

            result = _generate_keyframe("test prompt", config, output)

        assert result == output
        assert output.exists()
        assert output.stat().st_size > 0

    def test_raises_without_api_key(self, tmp_dir):
        from src.generator.video_pipeline import _generate_keyframe

        config = VideoGenerationConfig(openai_key="")

        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            with pytest.raises(ValueError, match="No OpenAI API key"):
                _generate_keyframe("prompt", config)

    def test_landscape_uses_wide_dalle_size(self, tmp_dir):
        from src.generator.video_pipeline import _generate_keyframe

        config = VideoGenerationConfig(
            width=1920, height=1080, openai_key="test-key"
        )

        with patch("src.generator.video_pipeline.httpx.Client") as MockClient:
            mock_client = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)

            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "data": [{"url": "https://example.com/img.png"}]
            }
            mock_resp.raise_for_status = MagicMock()

            mock_dl = MagicMock()
            mock_dl.content = b"\x89PNG" + b"\x00" * 500
            mock_dl.raise_for_status = MagicMock()

            mock_client.post.return_value = mock_resp
            mock_client.get.return_value = mock_dl

            _generate_keyframe("test", config, tmp_dir / "kf.png")

            # Check the payload sent to OpenAI
            post_call = mock_client.post.call_args
            payload = post_call.kwargs.get("json") or post_call[1].get("json")
            assert payload["size"] == "1792x1024"


# ---------------------------------------------------------------------------
# Animate keyframe tests (mocked API)
# ---------------------------------------------------------------------------

class TestAnimateKeyframe:
    """Test _animate_keyframe() routing and mocked generation."""

    def test_fal_model_routes_to_fal(self, tmp_dir):
        from src.generator.video_pipeline import _animate_keyframe

        config = VideoGenerationConfig(
            video_model="kling-v1", fal_key="test-fal-key"
        )
        keyframe = tmp_dir / "keyframe.png"
        keyframe.write_bytes(b"\x89PNG" + b"\x00" * 500)

        with patch("src.generator.video_pipeline._animate_keyframe_fal") as mock_fal:
            mock_fal.return_value = tmp_dir / "clip.mp4"
            result = _animate_keyframe(keyframe, "test prompt", 10.0, config)
            mock_fal.assert_called_once()
            assert result == tmp_dir / "clip.mp4"

    def test_replicate_model_routes_to_replicate(self, tmp_dir):
        from src.generator.video_pipeline import _animate_keyframe

        config = VideoGenerationConfig(
            video_model="runway-gen3", replicate_token="test-token"
        )
        keyframe = tmp_dir / "keyframe.png"
        keyframe.write_bytes(b"\x89PNG" + b"\x00" * 500)

        with patch(
            "src.generator.video_pipeline._animate_keyframe_replicate"
        ) as mock_rep:
            mock_rep.return_value = tmp_dir / "clip.mp4"
            result = _animate_keyframe(keyframe, "test prompt", 10.0, config)
            mock_rep.assert_called_once()

    def test_unsupported_model_raises(self, tmp_dir):
        from src.generator.video_pipeline import _animate_keyframe

        config = VideoGenerationConfig(video_model="nonexistent-model")
        keyframe = tmp_dir / "keyframe.png"
        keyframe.write_bytes(b"\x89PNG" + b"\x00" * 500)

        with pytest.raises(ValueError, match="Unsupported video model"):
            _animate_keyframe(keyframe, "prompt", 10.0, config)


# ---------------------------------------------------------------------------
# Extract last frame tests
# ---------------------------------------------------------------------------

class TestExtractLastFrame:
    """Test _extract_last_frame() with mocked ffmpeg."""

    def test_extract_last_frame_success(self, tmp_dir):
        video = tmp_dir / "video.mp4"
        video.write_bytes(b"\x00" * 5000)  # Fake video
        output = tmp_dir / "last_frame.png"

        def fake_run(cmd, **kwargs):
            # Write a fake PNG to the output path
            out_path = Path(cmd[-1])
            out_path.write_bytes(b"\x89PNG" + b"\x00" * 500)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("subprocess.run", side_effect=fake_run):
            result = _extract_last_frame(video, output)
            assert result == output
            assert output.exists()

    def test_extract_last_frame_fallback(self, tmp_dir):
        video = tmp_dir / "video.mp4"
        video.write_bytes(b"\x00" * 5000)
        output = tmp_dir / "frame.png"

        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First attempt fails
                return subprocess.CompletedProcess(cmd, 1, "", "error")
            else:
                # Fallback succeeds
                out_path = Path(cmd[-1])
                out_path.write_bytes(b"\x89PNG" + b"\x00" * 500)
                return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("subprocess.run", side_effect=fake_run):
            result = _extract_last_frame(video, output)
            assert result == output
            assert call_count[0] == 2  # Primary + fallback


# ---------------------------------------------------------------------------
# Stitch segments tests
# ---------------------------------------------------------------------------

class TestStitchSegments:
    """Test _stitch_segments() video stitching."""

    def test_single_segment_reencodes(self, tmp_dir):
        seg = tmp_dir / "seg.mp4"
        seg.write_bytes(b"\x00" * 5000)
        output = tmp_dir / "output.mp4"

        with patch("src.generator.video_pipeline._reencode_video") as mock_reencode:
            _stitch_segments([seg], output, target_duration=30.0, fps=60)
            mock_reencode.assert_called_once()
            args = mock_reencode.call_args
            assert args[0][2] == 30.0  # target_duration
            assert args[0][3] == 60  # fps

    def test_no_segments_raises(self, tmp_dir):
        with pytest.raises(ValueError, match="No segments"):
            _stitch_segments([], tmp_dir / "out.mp4", target_duration=30.0)

    def test_multiple_segments_stitch(self, tmp_dir):
        segs = []
        for i in range(3):
            seg = tmp_dir / f"seg_{i}.mp4"
            seg.write_bytes(b"\x00" * 5000)
            segs.append(seg)
        output = tmp_dir / "output.mp4"

        def fake_run(cmd, **kwargs):
            # Write output for any ffmpeg command
            out_path = None
            for j, arg in enumerate(cmd):
                if arg == "-map" or arg == "-f":
                    continue
                if j > 0 and cmd[j - 1] not in ("-i", "-f", "-filter_complex",
                                                   "-safe", "-vf", "-r", "-t",
                                                   "-c:v", "-preset", "-crf",
                                                   "-pix_fmt"):
                    # Heuristic: last non-flag arg is output
                    pass
            # Write to the last argument that looks like a path
            for arg in reversed(cmd):
                if arg.endswith(".mp4"):
                    Path(arg).parent.mkdir(parents=True, exist_ok=True)
                    Path(arg).write_bytes(b"\x00" * 3000)
                    break
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with patch("subprocess.run", side_effect=fake_run):
            with patch(
                "src.generator.video_pipeline._get_video_duration", return_value=10.0
            ):
                _stitch_segments(
                    segs, output, target_duration=30.0, fps=60, crossfade_duration=0.5
                )


# ---------------------------------------------------------------------------
# Full pipeline integration test (all APIs mocked)
# ---------------------------------------------------------------------------

class TestGenerateFullSongVideo:
    """Test generate_full_song_video() end-to-end with all APIs mocked."""

    def _make_fake_clip(self, base_dir: Path, index: list):
        """Create a unique fake clip file for each mock call."""
        def _side_effect(*args, **kwargs):
            i = index[0]
            index[0] += 1
            clip = base_dir / f"fake_clip_{i}.mp4"
            clip.parent.mkdir(parents=True, exist_ok=True)
            clip.write_bytes(b"\x00" * 5000)
            return clip
        return _side_effect

    def test_full_pipeline_runs(self, sample_analysis, tmp_dir):
        config = VideoGenerationConfig(
            video_model="kling-v1",
            openai_key="test-key",
            fal_key="test-fal-key",
            work_dir=str(tmp_dir / "work"),
            fps=30,
            crossfade_duration=0.5,
        )
        output = tmp_dir / "final.mp4"

        # Use a directory outside system temp so cleanup won't remove them
        fake_clips_dir = tmp_dir / "work" / "fake_clips"
        fake_clips_dir.mkdir(parents=True, exist_ok=True)

        fake_frame = tmp_dir / "work" / "fake_frame.png"
        fake_frame.parent.mkdir(parents=True, exist_ok=True)
        fake_frame.write_bytes(b"\x89PNG" + b"\x00" * 500)

        progress_calls = []

        def progress_cb(stage, current, total):
            progress_calls.append((stage, current, total))

        clip_index = [0]

        with patch(
            "src.generator.video_pipeline._generate_keyframe"
        ) as mock_kf, patch(
            "src.generator.video_pipeline._animate_keyframe",
            side_effect=self._make_fake_clip(fake_clips_dir, clip_index),
        ) as mock_animate, patch(
            "src.generator.video_pipeline._extract_last_frame"
        ) as mock_extract, patch(
            "src.generator.video_pipeline._stitch_segments"
        ) as mock_stitch:
            mock_kf.return_value = fake_frame
            mock_extract.return_value = fake_frame
            mock_stitch.return_value = output

            # Create the output so the return check passes
            output.write_bytes(b"\x00" * 1000)

            result = generate_full_song_video(
                analysis=sample_analysis,
                config=config,
                audio_duration=180.0,
                output_path=output,
                progress_callback=progress_cb,
            )

        assert result == output

        # 6 phrases of 30s each, max_segment_duration=10s -> 18 segments
        total_segs = clip_index[0]
        assert total_segs == 18

        # Keyframe generated for first segment only (others use chained frames)
        assert mock_kf.call_count == 1

        # Extract last frame called for segments 2-18 (chaining)
        assert mock_extract.call_count == total_segs - 1

        # Stitch called once
        mock_stitch.assert_called_once()

        # Progress callbacks fired
        stages = [c[0] for c in progress_calls]
        assert "plan" in stages
        assert "keyframe" in stages
        assert "animate" in stages
        assert "stitch" in stages

    def test_unsupported_model_raises(self, sample_analysis, tmp_dir):
        config = VideoGenerationConfig(video_model="fake-model")
        with pytest.raises(ValueError, match="Unsupported video model"):
            generate_full_song_video(
                analysis=sample_analysis,
                config=config,
                audio_duration=180.0,
                output_path=tmp_dir / "out.mp4",
            )

    def test_chaining_falls_back_to_fresh_keyframe(self, sample_analysis, tmp_dir):
        """When extracting last frame fails, falls back to generating a new keyframe."""
        config = VideoGenerationConfig(
            video_model="kling-v1",
            openai_key="test-key",
            fal_key="test-fal-key",
            work_dir=str(tmp_dir / "work"),
        )
        output = tmp_dir / "final.mp4"

        fake_clips_dir = tmp_dir / "work" / "fake_clips"
        fake_clips_dir.mkdir(parents=True, exist_ok=True)

        fake_frame = tmp_dir / "work" / "fake_frame.png"
        fake_frame.parent.mkdir(parents=True, exist_ok=True)
        fake_frame.write_bytes(b"\x89PNG" + b"\x00" * 500)

        clip_index = [0]

        with patch(
            "src.generator.video_pipeline._generate_keyframe"
        ) as mock_kf, patch(
            "src.generator.video_pipeline._animate_keyframe",
            side_effect=self._make_fake_clip(fake_clips_dir, clip_index),
        ), patch(
            "src.generator.video_pipeline._extract_last_frame",
            side_effect=RuntimeError("ffmpeg failed"),
        ), patch(
            "src.generator.video_pipeline._stitch_segments"
        ) as mock_stitch:
            mock_kf.return_value = fake_frame
            mock_stitch.return_value = output
            output.write_bytes(b"\x00" * 1000)

            result = generate_full_song_video(
                analysis=sample_analysis,
                config=config,
                audio_duration=180.0,
                output_path=output,
            )

        # All 18 keyframes should be freshly generated (no chaining worked)
        # 6 phrases x 30s each / 10s max_segment = 18 segments
        assert mock_kf.call_count == 18

    def test_progress_callback_optional(self, sample_analysis, tmp_dir):
        """Pipeline works without a progress callback."""
        config = VideoGenerationConfig(
            video_model="kling-v1",
            openai_key="test-key",
            fal_key="test-fal-key",
            work_dir=str(tmp_dir / "work"),
        )
        output = tmp_dir / "final.mp4"

        fake_clips_dir = tmp_dir / "work" / "fake_clips"
        fake_clips_dir.mkdir(parents=True, exist_ok=True)

        fake_frame = tmp_dir / "work" / "fake_frame.png"
        fake_frame.parent.mkdir(parents=True, exist_ok=True)
        fake_frame.write_bytes(b"\x89PNG" + b"\x00" * 500)

        clip_index = [0]

        with patch(
            "src.generator.video_pipeline._generate_keyframe", return_value=fake_frame
        ), patch(
            "src.generator.video_pipeline._animate_keyframe",
            side_effect=self._make_fake_clip(fake_clips_dir, clip_index),
        ), patch(
            "src.generator.video_pipeline._extract_last_frame", return_value=fake_frame
        ), patch(
            "src.generator.video_pipeline._stitch_segments", return_value=output
        ):
            output.write_bytes(b"\x00" * 1000)
            # Should not raise
            generate_full_song_video(
                analysis=sample_analysis,
                config=config,
                audio_duration=180.0,
                output_path=output,
                progress_callback=None,
            )


# ---------------------------------------------------------------------------
# VideoGenerationConfig tests
# ---------------------------------------------------------------------------

class TestVideoGenerationConfig:
    """Test VideoGenerationConfig dataclass."""

    def test_defaults(self):
        cfg = VideoGenerationConfig()
        assert cfg.width == 1920
        assert cfg.height == 1080
        assert cfg.fps == 60
        assert cfg.video_model == "kling-v1"
        assert cfg.image_model == "dall-e-3"
        assert cfg.quality == "high"

    def test_custom_values(self):
        cfg = VideoGenerationConfig(
            width=3840,
            height=2160,
            fps=30,
            video_model="minimax",
            quality="draft",
            style_prompt="cosmic nebula",
            fal_key="my-fal-key",
        )
        assert cfg.width == 3840
        assert cfg.video_model == "minimax"
        assert cfg.style_prompt == "cosmic nebula"
        assert cfg.fal_key == "my-fal-key"
