"""Tests for the thumbnail contact sheet generator."""
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from src.composer.thumbnails import (
    create_thumbnail_grid,
    _fit_thumbnail,
    _format_time,
    _energy_bar,
    _get_font,
)


def _make_test_video(path: Path, width: int = 320, height: int = 180, frames: int = 10):
    """Create a minimal test video using ffmpeg."""
    import subprocess

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=red:s={width}x{height}:d=0.5",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, timeout=30)


def test_create_thumbnail_grid_basic():
    """Test basic thumbnail grid creation with real video clips."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create test video clips
        clips = []
        for i, label in enumerate(["drop", "buildup", "breakdown", "intro"]):
            video_path = tmpdir / f"phrase_{i:03d}_{label}.mp4"
            _make_test_video(video_path)
            clips.append({
                "path": str(video_path),
                "label": label,
                "start": i * 15.0,
                "energy": 0.3 + i * 0.2,
                "phrase_idx": i,
            })

        analysis = {
            "title": "Test Track",
            "bpm": 128.0,
            "duration": 60.0,
            "phrases": [
                {"label": "drop", "energy": 0.9},
                {"label": "buildup", "energy": 0.6},
                {"label": "breakdown", "energy": 0.3},
                {"label": "intro", "energy": 0.2},
            ],
        }

        output_path = tmpdir / "thumbnails.png"
        result = create_thumbnail_grid(clips, analysis, output_path)

        assert result == output_path
        assert output_path.exists()
        assert output_path.stat().st_size > 1000

        # Verify it's a valid PNG
        img = Image.open(output_path)
        assert img.format == "PNG"
        assert img.width > 200
        assert img.height > 200


def test_create_thumbnail_grid_no_clips():
    """Test with empty clips list creates placeholder."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "empty.png"
        result = create_thumbnail_grid([], {}, output_path)
        assert output_path.exists()


def test_create_thumbnail_grid_missing_files():
    """Test with clips pointing to non-existent files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        clips = [
            {"path": "/nonexistent/video.mp4", "label": "drop", "start": 0, "phrase_idx": 0},
        ]
        output_path = Path(tmpdir) / "missing.png"
        result = create_thumbnail_grid(clips, {"title": "Test"}, output_path)
        assert output_path.exists()


def test_create_thumbnail_grid_custom_thumb_size():
    """Test with custom thumbnail size."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        video_path = tmpdir / "clip.mp4"
        _make_test_video(video_path)

        clips = [{"path": str(video_path), "label": "drop", "start": 0, "phrase_idx": 0}]
        output_path = tmpdir / "thumb.png"
        create_thumbnail_grid(clips, {"title": "Test", "bpm": 128}, output_path,
                              config={"thumb_size": 100})
        assert output_path.exists()


def test_create_thumbnail_grid_multiple_same_type():
    """Test with multiple clips of the same phrase type (multiple columns)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        clips = []
        for i in range(3):
            video_path = tmpdir / f"drop_{i}.mp4"
            _make_test_video(video_path)
            clips.append({
                "path": str(video_path),
                "label": "drop",
                "start": i * 8.0,
                "phrase_idx": i,
            })

        analysis = {"title": "Multi Drop", "bpm": 140, "duration": 30,
                     "phrases": [{"energy": 0.8}] * 3}
        output_path = tmpdir / "multi.png"
        result = create_thumbnail_grid(clips, analysis, output_path)
        assert output_path.exists()


def test_fit_thumbnail_wide_image():
    """Test fitting a wide image into a square thumbnail."""
    wide = Image.new("RGB", (400, 200), (255, 0, 0))
    result = _fit_thumbnail(wide, 100)
    assert result.size == (100, 100)


def test_fit_thumbnail_tall_image():
    """Test fitting a tall image into a square thumbnail."""
    tall = Image.new("RGB", (200, 400), (0, 255, 0))
    result = _fit_thumbnail(tall, 100)
    assert result.size == (100, 100)


def test_fit_thumbnail_already_correct():
    """Test that correctly sized image is returned as-is."""
    exact = Image.new("RGB", (100, 100), (0, 0, 255))
    result = _fit_thumbnail(exact, 100)
    assert result.size == (100, 100)


def test_format_time():
    """Test time formatting."""
    assert _format_time(0) == "0:00"
    assert _format_time(65) == "1:05"
    assert _format_time(130.5) == "2:10"


def test_energy_bar():
    """Test energy bar text representation."""
    assert _energy_bar(0.0) == "....."
    assert _energy_bar(1.0) == "|||||"
    assert _energy_bar(0.6) == "|||.."


def test_get_font():
    """Test font loading (should always return a usable font)."""
    font = _get_font(14)
    assert font is not None
