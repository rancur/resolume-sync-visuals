"""
Tests for src.encoder — video assembly and encoding pipeline.

Uses real small test videos generated via ffmpeg (lavfi testsrc).
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from src.encoder import (
    encode_for_resolume,
    extract_frame,
    get_video_info,
    name_for_resolume,
    pad_or_trim,
    stitch_videos,
    upscale_fps,
)

# ---------------------------------------------------------------------------
# Fixtures — generate tiny test videos via ffmpeg testsrc
# ---------------------------------------------------------------------------

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def _make_test_video(
    path: Path,
    duration: float = 2.0,
    fps: int = 30,
    width: int = 320,
    height: int = 240,
    color: str = "red",
) -> Path:
    """Create a tiny test video using ffmpeg color source."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={color}:s={width}x{height}:r={fps}:d={duration}",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return path


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that gets cleaned up."""
    d = Path(tempfile.mkdtemp(prefix="rsv_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def test_video(tmp_dir) -> Path:
    """A 2-second red test video at 320x240, 30fps."""
    return _make_test_video(tmp_dir / "test.mp4")


@pytest.fixture
def test_video_blue(tmp_dir) -> Path:
    """A 2-second blue test video."""
    return _make_test_video(tmp_dir / "blue.mp4", color="blue")


@pytest.fixture
def test_video_green(tmp_dir) -> Path:
    """A 2-second green test video."""
    return _make_test_video(tmp_dir / "green.mp4", color="green")


@pytest.fixture
def short_video(tmp_dir) -> Path:
    """A 1-second short test video."""
    return _make_test_video(tmp_dir / "short.mp4", duration=1.0)


@pytest.fixture
def low_fps_video(tmp_dir) -> Path:
    """A 24fps test video for upscaling tests."""
    return _make_test_video(tmp_dir / "low_fps.mp4", fps=24, duration=1.0)


# ---------------------------------------------------------------------------
# get_video_info
# ---------------------------------------------------------------------------


class TestGetVideoInfo:
    def test_basic_info(self, test_video):
        info = get_video_info(test_video)
        assert info["width"] == 320
        assert info["height"] == 240
        assert info["codec"] == "h264"
        assert info["size_bytes"] > 0
        assert 1.5 < info["duration"] < 2.5
        assert info["fps"] > 0

    def test_file_not_found(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            get_video_info(tmp_dir / "nonexistent.mp4")

    def test_duration_accuracy(self, test_video):
        info = get_video_info(test_video)
        # Should be close to 2.0 seconds
        assert abs(info["duration"] - 2.0) < 0.2


# ---------------------------------------------------------------------------
# extract_frame
# ---------------------------------------------------------------------------


class TestExtractFrame:
    def test_extract_at_zero(self, test_video, tmp_dir):
        out = tmp_dir / "frame.jpg"
        result = extract_frame(test_video, 0.0, out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 100

    def test_extract_at_one_second(self, test_video, tmp_dir):
        out = tmp_dir / "frame_1s.png"
        result = extract_frame(test_video, 1.0, out)
        assert result.exists()
        assert result.stat().st_size > 100

    def test_creates_parent_dirs(self, test_video, tmp_dir):
        out = tmp_dir / "sub" / "dir" / "frame.jpg"
        result = extract_frame(test_video, 0.5, out)
        assert result.exists()


# ---------------------------------------------------------------------------
# pad_or_trim
# ---------------------------------------------------------------------------


class TestPadOrTrim:
    def test_trim_longer_video(self, test_video, tmp_dir):
        """2s video trimmed to 1.5s."""
        out = tmp_dir / "trimmed.mp4"
        pad_or_trim(test_video, out, target_duration=1.5)
        info = get_video_info(out)
        assert abs(info["duration"] - 1.5) < 0.2

    def test_pad_shorter_video(self, short_video, tmp_dir):
        """1s video padded to 3s by looping."""
        out = tmp_dir / "padded.mp4"
        pad_or_trim(short_video, out, target_duration=3.0)
        info = get_video_info(out)
        assert abs(info["duration"] - 3.0) < 0.2

    def test_exact_duration_passthrough(self, test_video, tmp_dir):
        """Video already at target duration is just copied."""
        info_before = get_video_info(test_video)
        out = tmp_dir / "same.mp4"
        pad_or_trim(test_video, out, target_duration=info_before["duration"])
        assert out.exists()
        info_after = get_video_info(out)
        assert abs(info_after["duration"] - info_before["duration"]) < 0.1


# ---------------------------------------------------------------------------
# upscale_fps
# ---------------------------------------------------------------------------


class TestUpscaleFps:
    def test_upscale_24_to_60(self, low_fps_video, tmp_dir):
        out = tmp_dir / "upscaled.mp4"
        upscale_fps(low_fps_video, out, target_fps=60)
        assert out.exists()
        info = get_video_info(out)
        assert info["fps"] >= 59.0  # Allow slight rounding

    def test_upscale_creates_output(self, low_fps_video, tmp_dir):
        out = tmp_dir / "sub" / "upscaled.mp4"
        upscale_fps(low_fps_video, out, target_fps=30)
        assert out.exists()
        assert out.stat().st_size > 100


# ---------------------------------------------------------------------------
# stitch_videos
# ---------------------------------------------------------------------------


class TestStitchVideos:
    def test_single_segment(self, test_video, tmp_dir):
        """Single segment — pads/trims to target duration."""
        out = tmp_dir / "stitched.mp4"
        stitch_videos([test_video], out, target_duration=1.5)
        info = get_video_info(out)
        assert abs(info["duration"] - 1.5) < 0.2

    def test_two_segments_crossfade(self, test_video, test_video_blue, tmp_dir):
        """Two segments stitched with crossfade."""
        out = tmp_dir / "stitched.mp4"
        stitch_videos(
            [test_video, test_video_blue],
            out,
            target_duration=3.0,
            crossfade_seconds=0.5,
            fps=30,
        )
        assert out.exists()
        info = get_video_info(out)
        assert abs(info["duration"] - 3.0) < 0.3

    def test_three_segments(self, test_video, test_video_blue, test_video_green, tmp_dir):
        """Three segments stitched with crossfades."""
        out = tmp_dir / "stitched3.mp4"
        stitch_videos(
            [test_video, test_video_blue, test_video_green],
            out,
            target_duration=5.0,
            crossfade_seconds=0.5,
            fps=30,
        )
        assert out.exists()
        info = get_video_info(out)
        assert abs(info["duration"] - 5.0) < 0.5

    def test_empty_segments_raises(self, tmp_dir):
        with pytest.raises(ValueError, match="No segments"):
            stitch_videos([], tmp_dir / "out.mp4", target_duration=5.0)

    def test_stitch_with_looping(self, short_video, tmp_dir):
        """If total < target, last segment loops to fill."""
        out = tmp_dir / "looped.mp4"
        stitch_videos([short_video], out, target_duration=5.0)
        info = get_video_info(out)
        assert abs(info["duration"] - 5.0) < 0.2


# ---------------------------------------------------------------------------
# encode_for_resolume
# ---------------------------------------------------------------------------


class TestEncodeForResolume:
    def test_dxv_encoding(self, test_video, tmp_dir):
        """Encode to DXV — Resolume native codec."""
        out = tmp_dir / "output.mov"
        encode_for_resolume(test_video, out, codec="dxv", fps=30, width=320, height=240)
        assert out.exists()
        info = get_video_info(out)
        assert info["codec"] == "dxv"
        assert info["width"] == 320
        assert info["height"] == 240
        # DXV files are large — even tiny test videos should be substantial
        assert info["size_bytes"] > 1000

    def test_dxv_1080p_scaling(self, test_video, tmp_dir):
        """DXV encoding with upscale to 1080p."""
        out = tmp_dir / "output_1080.mov"
        encode_for_resolume(test_video, out, codec="dxv", fps=30, width=1920, height=1080)
        assert out.exists()
        info = get_video_info(out)
        assert info["width"] == 1920
        assert info["height"] == 1080

    def test_invalid_codec_raises(self, test_video, tmp_dir):
        with pytest.raises(ValueError, match="Unsupported codec"):
            encode_for_resolume(test_video, tmp_dir / "out.mov", codec="prores")

    def test_hap_encoding_if_available(self, test_video, tmp_dir):
        """HAP encoding — skip if codec not available in this ffmpeg build."""
        out = tmp_dir / "output_hap.mov"
        try:
            encode_for_resolume(test_video, out, codec="hap", fps=30, width=320, height=240)
            assert out.exists()
            info = get_video_info(out)
            assert info["codec"] == "hap"
        except RuntimeError as e:
            if "Unknown encoder" in str(e) or "Encoder hap" in str(e) or "hap" in str(e).lower():
                pytest.skip("HAP encoder not available in this ffmpeg build")
            raise


# ---------------------------------------------------------------------------
# name_for_resolume
# ---------------------------------------------------------------------------


class TestNameForResolume:
    def test_basic_title(self):
        assert name_for_resolume("My Track") == "My Track.mov"

    def test_title_with_artist(self):
        assert name_for_resolume("My Track", artist="DJ Name") == "My Track - DJ Name.mov"

    def test_custom_extension(self):
        assert name_for_resolume("My Track", extension=".mp4") == "My Track.mp4"

    def test_extension_without_dot(self):
        assert name_for_resolume("My Track", extension="avi") == "My Track.avi"

    def test_sanitizes_unsafe_chars(self):
        name = name_for_resolume('Track: "Remix" <V2>')
        assert ":" not in name
        assert '"' not in name
        assert "<" not in name
        assert ">" not in name
        assert name.endswith(".mov")

    def test_collapses_whitespace(self):
        name = name_for_resolume("Track   Name  Here")
        assert name == "Track Name Here.mov"

    def test_empty_title_raises(self):
        with pytest.raises(ValueError, match="track_title"):
            name_for_resolume("")

    def test_path_separators_removed(self):
        name = name_for_resolume("Track/With\\Slashes")
        assert "/" not in name
        assert "\\" not in name
