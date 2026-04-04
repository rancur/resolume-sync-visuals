"""Tests for the video model module (offline -- no API keys needed)."""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.generator.video_models import (
    AVAILABLE_VIDEO_MODELS,
    _get_model_config,
    _resolve_token,
    apply_beat_sync_effects,
    generate_video_clip,
    make_seamless_loop,
)


class TestModelConfig:
    """Test model configuration and lookup."""

    def test_available_models_have_required_fields(self):
        """All models have required fields."""
        for name, cfg in AVAILABLE_VIDEO_MODELS.items():
            assert "id" in cfg, f"{name} missing 'id'"
            assert "max_duration" in cfg, f"{name} missing 'max_duration'"
            assert "cost" in cfg, f"{name} missing 'cost'"
            assert cfg["max_duration"] > 0
            assert cfg["cost"] > 0

    def test_at_least_three_models(self):
        """At least three video models are available."""
        assert len(AVAILABLE_VIDEO_MODELS) >= 3

    def test_known_models_present(self):
        """Known model short names exist."""
        assert "wan2.1-480p" in AVAILABLE_VIDEO_MODELS
        assert "wan2.1-720p" in AVAILABLE_VIDEO_MODELS
        assert "minimax-live" in AVAILABLE_VIDEO_MODELS

    def test_model_costs_reasonable(self):
        """Model costs are in expected range."""
        for name, cfg in AVAILABLE_VIDEO_MODELS.items():
            assert 0.01 <= cfg["cost"] <= 5.0, f"Model {name} cost ${cfg['cost']} seems wrong"

    def test_get_model_config_short_name(self):
        """Look up model by short name."""
        cfg = _get_model_config("wan2.1-480p")
        assert cfg["id"] == "fal-ai/wan/v2.1/text-to-video/480p"

    def test_get_model_config_full_id(self):
        """Look up model by full fal.ai model ID."""
        cfg = _get_model_config("fal-ai/wan/v2.1/text-to-video/720p")
        assert cfg["id"] == "fal-ai/wan/v2.1/text-to-video/720p"
        assert cfg["max_duration"] == 5

    def test_get_model_config_unknown(self):
        """Unknown model returns basic config with the ID passed through."""
        cfg = _get_model_config("some-org/custom-model")
        assert cfg["id"] == "some-org/custom-model"
        assert "max_duration" in cfg
        assert "cost" in cfg

    def test_minimax_model_config(self):
        """minimax-live has correct config."""
        cfg = AVAILABLE_VIDEO_MODELS["minimax-live"]
        assert "minimax" in cfg["id"]
        assert cfg["max_duration"] >= 5


class TestResolveToken:
    """Test token resolution."""

    def test_explicit_token(self):
        """Explicit token takes precedence."""
        assert _resolve_token("my-token") == "my-token"

    def test_missing_token_raises(self):
        """Missing token raises ValueError."""
        with patch("src.generator.video_models.REPLICATE_API_TOKEN", ""):
            with pytest.raises(ValueError, match="No Replicate API token"):
                _resolve_token("")

    def test_env_token_fallback(self):
        """Falls back to module-level env token."""
        with patch("src.generator.video_models.REPLICATE_API_TOKEN", "env-token"):
            assert _resolve_token("") == "env-token"


class TestGenerateVideoClip:
    """Test video generation with mocked API."""

    def test_missing_token_raises(self):
        """No token available raises ValueError."""
        with patch("src.generator.video_models.REPLICATE_API_TOKEN", ""):
            with pytest.raises(ValueError, match="No Replicate API token"):
                generate_video_clip(
                    prompt="test",
                    duration_seconds=3.0,
                    model="wan2.1-480p",
                    replicate_token="",
                )

    @patch("src.generator.video_models._download_video")
    @patch("src.generator.video_models._poll_prediction")
    @patch("src.generator.video_models.httpx.Client")
    def test_successful_generation(self, mock_client_cls, mock_poll, mock_download):
        """Successful API flow returns a Path."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        mock_response = MagicMock()
        mock_response.json.return_value = {"id": "pred_123"}
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        mock_poll.return_value = "https://example.com/video.mp4"

        tmpdir = tempfile.mkdtemp()
        video_path = Path(tmpdir) / "result.mp4"
        video_path.write_bytes(b"\x00" * 5000)
        mock_download.return_value = video_path

        result = generate_video_clip(
            prompt="neon particles flowing",
            duration_seconds=4.0,
            model="wan2.1-480p",
            replicate_token="test-token",
        )

        assert result is not None
        assert result.exists()
        shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("src.generator.video_models.httpx.Client")
    def test_api_error_returns_none(self, mock_client_cls):
        """API error returns None gracefully."""
        import httpx

        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=MagicMock(status_code=400, text="bad")
        )
        mock_client.post.return_value = mock_response

        result = generate_video_clip(
            prompt="test",
            duration_seconds=3.0,
            replicate_token="test-token",
        )
        assert result is None

    def test_duration_clamping_no_token(self):
        """Requesting with no token raises ValueError."""
        with patch("src.generator.video_models.REPLICATE_API_TOKEN", ""):
            with pytest.raises(ValueError):
                generate_video_clip(
                    prompt="test",
                    duration_seconds=100.0,
                    model="wan2.1-480p",
                )


class TestMakeSeamlessLoop:
    """Test seamless loop creation."""

    def test_seamless_loop_fallback_on_no_ffprobe(self):
        """Falls back to copy when ffprobe/ffmpeg unavailable or fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.mp4"
            src.write_bytes(b"\x00" * 2000)

            out = Path(tmpdir) / "loop.mp4"
            result = make_seamless_loop(src, out, loop_duration=4.0)
            assert result.exists()

    def test_output_parent_dirs_created(self):
        """Output parent directories are created if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.mp4"
            src.write_bytes(b"\x00" * 2000)

            out = Path(tmpdir) / "subdir" / "nested" / "loop.mp4"
            result = make_seamless_loop(src, out, loop_duration=4.0)
            assert result.parent.exists()

    def test_returns_path_object(self):
        """Return value is always a Path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.mp4"
            src.write_bytes(b"\x00" * 2000)

            out = Path(tmpdir) / "loop.mp4"
            result = make_seamless_loop(src, out, loop_duration=4.0)
            assert isinstance(result, Path)


class TestBeatSyncEffects:
    """Test beat sync post-processing."""

    def test_no_effects_copies_source(self):
        """When effects are near zero, source is copied unchanged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.mp4"
            src.write_bytes(b"\x00" * 2000)

            out = Path(tmpdir) / "processed.mp4"
            effects = {"beat_flash_intensity": 0.0, "zoom_pulse": 0.0}
            phrase = {"energy": 0.5, "label": "intro"}

            result = apply_beat_sync_effects(src, out, bpm=128.0, phrase=phrase, effects=effects)
            assert result.exists()
            assert result.stat().st_size == src.stat().st_size

    def test_effects_with_high_energy_no_crash(self):
        """High energy effects don't crash (falls back to copy with dummy data)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.mp4"
            src.write_bytes(b"\x00" * 2000)

            out = Path(tmpdir) / "processed.mp4"
            effects = {"beat_flash_intensity": 0.8, "zoom_pulse": 0.1}
            phrase = {"energy": 1.0, "label": "drop"}

            result = apply_beat_sync_effects(src, out, bpm=140.0, phrase=phrase, effects=effects)
            assert result.exists()

    def test_output_dir_created(self):
        """Output parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.mp4"
            src.write_bytes(b"\x00" * 2000)

            out = Path(tmpdir) / "deep" / "dir" / "processed.mp4"
            effects = {"beat_flash_intensity": 0.0, "zoom_pulse": 0.0}
            phrase = {"energy": 0.5, "label": "intro"}

            result = apply_beat_sync_effects(src, out, bpm=128.0, phrase=phrase, effects=effects)
            assert result.parent.exists()

    def test_empty_effects_dict(self):
        """Empty effects dict means no processing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.mp4"
            src.write_bytes(b"\x00" * 2000)

            out = Path(tmpdir) / "processed.mp4"
            result = apply_beat_sync_effects(
                src, out, bpm=128.0, phrase={"energy": 0.5, "label": "drop"}, effects={}
            )
            assert result.exists()
            assert result.stat().st_size == src.stat().st_size
