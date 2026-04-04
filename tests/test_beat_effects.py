"""Tests for beat-synced post-processing effects."""
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import importlib.util as _ilu

# Import directly to avoid __init__.py pulling in engine.py (which uses
# Python 3.10+ union syntax on 3.9).
_spec = _ilu.spec_from_file_location(
    "beat_effects",
    str(Path(__file__).resolve().parent.parent / "src" / "generator" / "beat_effects.py"),
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

SECTION_INTENSITIES = _mod.SECTION_INTENSITIES
add_beat_sync_effects = _mod.add_beat_sync_effects
get_bar_interval = _mod.get_bar_interval
get_beat_interval = _mod.get_beat_interval
_probe_video = _mod._probe_video


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_video(path: Path, duration: float = 1.0, width: int = 320, height: int = 180):
    """Create a tiny test video with ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=red:s={width}x{height}:d={duration}:r=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    assert result.returncode == 0, f"Failed to create test video: {result.stderr.decode()}"


# ---------------------------------------------------------------------------
# Unit tests — no ffmpeg needed
# ---------------------------------------------------------------------------

class TestGetBeatInterval:
    def test_128_bpm(self):
        assert abs(get_beat_interval(128) - 0.46875) < 1e-6

    def test_175_bpm(self):
        assert abs(get_beat_interval(175) - 60.0 / 175) < 1e-6

    def test_zero_bpm_raises(self):
        with pytest.raises(ValueError, match="positive"):
            get_beat_interval(0)

    def test_negative_bpm_raises(self):
        with pytest.raises(ValueError, match="positive"):
            get_beat_interval(-100)


class TestGetBarInterval:
    def test_128_bpm(self):
        assert abs(get_bar_interval(128) - 0.46875 * 4) < 1e-6

    def test_is_4x_beat(self):
        for bpm in [100, 128, 140, 175]:
            assert abs(get_bar_interval(bpm) - get_beat_interval(bpm) * 4) < 1e-9


class TestSectionIntensities:
    def test_all_sections_have_flash_and_zoom(self):
        for section, params in SECTION_INTENSITIES.items():
            assert "flash" in params, f"Missing flash for {section}"
            assert "zoom" in params, f"Missing zoom for {section}"

    def test_drop_is_highest(self):
        drop = SECTION_INTENSITIES["drop"]
        for section, params in SECTION_INTENSITIES.items():
            if section == "drop":
                continue
            assert params["flash"] <= drop["flash"], f"{section} flash > drop"
            assert params["zoom"] <= drop["zoom"], f"{section} zoom > drop"


class TestBeatSyncEffectsValidation:
    """Test argument validation without running ffmpeg."""

    def test_missing_input_file(self):
        with pytest.raises(FileNotFoundError):
            add_beat_sync_effects(
                Path("/nonexistent/video.mp4"),
                Path("/tmp/out.mp4"),
                bpm=128,
            )

    def test_zero_bpm(self, tmp_path):
        fake_input = tmp_path / "input.mp4"
        fake_input.touch()
        with pytest.raises(ValueError, match="positive"):
            add_beat_sync_effects(fake_input, tmp_path / "out.mp4", bpm=0)

    def test_negative_bpm(self, tmp_path):
        fake_input = tmp_path / "input.mp4"
        fake_input.touch()
        with pytest.raises(ValueError, match="positive"):
            add_beat_sync_effects(fake_input, tmp_path / "out.mp4", bpm=-120)


# ---------------------------------------------------------------------------
# Integration tests — require ffmpeg
# ---------------------------------------------------------------------------

@pytest.fixture
def test_video(tmp_path):
    """Create a small test video."""
    video = tmp_path / "test_input.mp4"
    _make_test_video(video, duration=1.0)
    return video


class TestBeatSyncEffectsIntegration:
    """Integration tests that run ffmpeg."""

    @pytest.mark.skipif(
        not shutil.which("ffmpeg"),
        reason="ffmpeg not installed",
    )
    def test_basic_drop(self, test_video, tmp_path):
        output = tmp_path / "output.mp4"
        result = add_beat_sync_effects(
            test_video, output, bpm=128, section_label="drop", energy=0.8,
        )
        assert result == output
        assert output.exists()
        assert output.stat().st_size > 100

    @pytest.mark.skipif(
        not shutil.which("ffmpeg"),
        reason="ffmpeg not installed",
    )
    def test_intro_section(self, test_video, tmp_path):
        output = tmp_path / "output_intro.mp4"
        result = add_beat_sync_effects(
            test_video, output, bpm=140, section_label="intro", energy=0.3,
        )
        assert output.exists()
        assert output.stat().st_size > 100

    @pytest.mark.skipif(
        not shutil.which("ffmpeg"),
        reason="ffmpeg not installed",
    )
    def test_unknown_section_defaults_to_drop(self, test_video, tmp_path):
        output = tmp_path / "output_unknown.mp4"
        result = add_beat_sync_effects(
            test_video, output, bpm=175, section_label="verse", energy=0.5,
        )
        assert output.exists()

    @pytest.mark.skipif(
        not shutil.which("ffmpeg"),
        reason="ffmpeg not installed",
    )
    def test_output_dir_created(self, test_video, tmp_path):
        output = tmp_path / "nested" / "deep" / "output.mp4"
        result = add_beat_sync_effects(
            test_video, output, bpm=128, section_label="drop", energy=0.5,
        )
        assert output.exists()

    @pytest.mark.skipif(
        not shutil.which("ffmpeg"),
        reason="ffmpeg not installed",
    )
    def test_high_bpm_dnb(self, test_video, tmp_path):
        output = tmp_path / "output_dnb.mp4"
        result = add_beat_sync_effects(
            test_video, output, bpm=175, section_label="drop", energy=0.9,
        )
        assert output.exists()


class TestProbeVideo:
    @pytest.mark.skipif(
        not shutil.which("ffprobe"),
        reason="ffprobe not installed",
    )
    def test_probe_returns_dimensions(self, test_video):
        info = _probe_video(test_video)
        assert info["width"] == 320
        assert info["height"] == 180
        assert info["fps"] == 30

    def test_probe_nonexistent_returns_defaults(self, tmp_path):
        info = _probe_video(tmp_path / "nope.mp4")
        assert info["width"] == 1920
        assert info["height"] == 1080
        assert info["fps"] == 30
