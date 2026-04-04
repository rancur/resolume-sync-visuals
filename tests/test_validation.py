"""Tests for centralized validation utilities."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import soundfile as sf

from src.validation import (
    validate_audio_file,
    validate_style_config,
    validate_output_video,
    check_disk_space,
    check_dependencies,
    validate_api_key,
    check_mood_models,
)


# ---------------------------------------------------------------------------
# Audio file validation
# ---------------------------------------------------------------------------

class TestValidateAudioFile:
    def test_valid_wav(self, tmp_path):
        """Valid WAV file passes validation."""
        wav = tmp_path / "good.wav"
        y = np.sin(2 * np.pi * 440 * np.arange(22050) / 22050).astype(np.float32)
        sf.write(str(wav), y, 22050)

        ok, err = validate_audio_file(str(wav))
        assert ok is True
        assert err == ""

    def test_nonexistent_file(self):
        ok, err = validate_audio_file("/nonexistent/audio.wav")
        assert ok is False
        assert "not found" in err.lower() or "File not found" in err

    def test_empty_file(self, tmp_path):
        empty = tmp_path / "empty.wav"
        empty.write_bytes(b"")

        ok, err = validate_audio_file(str(empty))
        assert ok is False
        assert "empty" in err.lower() or "0 bytes" in err

    def test_corrupted_file(self, tmp_path):
        """Random bytes that aren't valid audio."""
        bad = tmp_path / "corrupted.wav"
        bad.write_bytes(os.urandom(1024))

        ok, err = validate_audio_file(str(bad))
        assert ok is False
        assert "cannot read" in err.lower() or "error" in err.lower() or err != ""

    def test_directory_instead_of_file(self, tmp_path):
        ok, err = validate_audio_file(str(tmp_path))
        assert ok is False
        assert "not a file" in err.lower()


# ---------------------------------------------------------------------------
# Style config validation
# ---------------------------------------------------------------------------

class TestValidateStyleConfig:
    def test_valid_full_config(self):
        config = {
            "prompts": {
                "base": "abstract art",
                "drop": "explosive",
                "buildup": "building energy",
                "breakdown": "calm",
                "intro": "emerging",
                "outro": "fading",
            },
            "colors": {
                "primary": "#FF0000",
                "secondary": "#00FF00",
            },
        }
        ok, warnings = validate_style_config(config)
        assert ok is True
        assert len(warnings) == 0

    def test_minimal_config_with_base(self):
        config = {"prompts": {"base": "abstract art"}}
        ok, warnings = validate_style_config(config)
        assert ok is True
        # Should warn about missing phrase prompts and colors
        assert any("colors" in w.lower() for w in warnings)
        assert any("drop" in w for w in warnings)

    def test_missing_prompts(self):
        config = {"colors": {"primary": "#FF0000"}}
        ok, warnings = validate_style_config(config)
        assert ok is False
        assert any("prompts" in w.lower() for w in warnings)

    def test_not_a_dict(self):
        ok, warnings = validate_style_config("not a dict")
        assert ok is False

    def test_prompts_not_dict(self):
        config = {"prompts": "just a string"}
        ok, warnings = validate_style_config(config)
        assert ok is False

    def test_missing_base_prompt(self):
        config = {"prompts": {"drop": "explosive"}}
        ok, warnings = validate_style_config(config)
        # Still ok (has some prompts), but warns about missing base
        assert ok is True
        assert any("base" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Output video validation
# ---------------------------------------------------------------------------

class TestValidateOutputVideo:
    def test_nonexistent_video(self):
        result = validate_output_video("/nonexistent/video.mp4")
        assert result.valid is False
        assert any("does not exist" in e.lower() or "not found" in e.lower() for e in result.errors)

    def test_tiny_file(self, tmp_path):
        tiny = tmp_path / "tiny.mp4"
        tiny.write_bytes(b"x" * 100)

        result = validate_output_video(str(tiny))
        assert result.valid is False
        assert any("small" in e.lower() or "1KB" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Disk space
# ---------------------------------------------------------------------------

class TestCheckDiskSpace:
    def test_current_directory_has_space(self):
        ok, available = check_disk_space(".", required_mb=1)
        assert ok is True
        assert available > 0

    def test_unreasonable_requirement(self):
        # 999 TB should fail
        ok, available = check_disk_space(".", required_mb=999_000_000)
        assert ok is False
        assert available > 0  # still reports available

    def test_nonexistent_path_walks_up(self, tmp_path):
        deep = str(tmp_path / "a" / "b" / "c" / "d")
        ok, available = check_disk_space(deep, required_mb=1)
        assert ok is True
        assert available > 0


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

class TestCheckDependencies:
    def test_python_version(self):
        deps = check_dependencies()
        assert "python" in deps
        assert deps["python"]["available"] is True
        assert deps["python"]["version"]  # non-empty

    def test_has_ffmpeg_keys(self):
        deps = check_dependencies()
        assert "ffmpeg" in deps
        assert "ffprobe" in deps
        # These tools should be available in the dev environment
        for tool in ("ffmpeg", "ffprobe"):
            assert "available" in deps[tool]
            assert "version" in deps[tool]


# ---------------------------------------------------------------------------
# API key validation
# ---------------------------------------------------------------------------

class TestValidateApiKey:
    def test_openai_valid(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-abc123def456ghi789jklmnopqrst"}):
            ok, msg = validate_api_key("openai")
            assert ok is True

    def test_openai_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            # Also need to clear the key if set
            env = os.environ.copy()
            env.pop("OPENAI_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                ok, msg = validate_api_key("openai")
                assert ok is False
                assert "not set" in msg

    def test_openai_bad_prefix(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "pk-wrong-prefix-abcdefghij"}):
            ok, msg = validate_api_key("openai")
            assert ok is False
            assert "sk-" in msg

    def test_openai_too_short(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-short"}):
            ok, msg = validate_api_key("openai")
            assert ok is False
            assert "short" in msg.lower()

    def test_replicate_valid(self):
        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "r8_abc123def456ghi789jklmnopqrst"}):
            ok, msg = validate_api_key("replicate")
            assert ok is True

    def test_replicate_missing(self):
        env = os.environ.copy()
        env.pop("REPLICATE_API_TOKEN", None)
        with patch.dict(os.environ, env, clear=True):
            ok, msg = validate_api_key("replicate")
            assert ok is False

    def test_replicate_bad_prefix(self):
        with patch.dict(os.environ, {"REPLICATE_API_TOKEN": "bad-prefix-abcdefghijklmnop"}):
            ok, msg = validate_api_key("replicate")
            assert ok is False
            assert "r8_" in msg

    def test_unknown_backend(self):
        ok, msg = validate_api_key("unknown")
        assert ok is False
        assert "unknown" in msg.lower()


# ---------------------------------------------------------------------------
# Corrupted audio handling in analyze_track
# ---------------------------------------------------------------------------

class TestCorruptedAudioHandling:
    def test_corrupted_audio_raises_runtime_error(self, tmp_path):
        """analyze_track should raise RuntimeError with a clear message for corrupted files."""
        from src.analyzer.audio import analyze_track

        bad = tmp_path / "corrupt.wav"
        bad.write_bytes(os.urandom(2048))

        with pytest.raises(RuntimeError, match="Failed to load audio"):
            analyze_track(str(bad))

    def test_nonexistent_audio_raises(self):
        from src.analyzer.audio import analyze_track

        with pytest.raises(Exception):
            analyze_track("/nonexistent/track.flac")


# ---------------------------------------------------------------------------
# Mood models check
# ---------------------------------------------------------------------------

class TestCheckMoodModels:
    def test_reports_missing_models(self):
        """Should report status (likely missing in test env)."""
        ok, msg = check_mood_models()
        # In test env, models may or may not exist -- just ensure it doesn't crash
        assert isinstance(ok, bool)
        assert isinstance(msg, str)
        assert len(msg) > 0
