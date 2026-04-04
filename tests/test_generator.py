"""Tests for the video generation engine (offline — no API keys needed)."""
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from src.generator.engine import (
    GenerationConfig,
    _create_beat_synced_loop,
    _resize_and_crop,
    _auto_loop_beats,
    _beat_pulse,
    _beat_flash,
)


def _make_test_keyframes(n=3, width=320, height=180):
    """Create test keyframe images."""
    keyframes = []
    tmpdir = tempfile.mkdtemp()
    for i in range(n):
        # Different colored frames
        arr = np.zeros((height, width, 3), dtype=np.uint8)
        arr[:, :, i % 3] = 200  # R, G, or B dominant
        img = Image.fromarray(arr)
        path = Path(tmpdir) / f"kf_{i}.png"
        img.save(str(path))
        keyframes.append(path)
    return keyframes


def test_beat_synced_loop_creates_video():
    """Test that beat-synced loop creation produces a valid video file."""
    keyframes = _make_test_keyframes(n=3, width=320, height=180)

    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test_loop.mp4"
        config = GenerationConfig(width=320, height=180, fps=24, quality="draft")
        phrase = {"label": "drop", "energy": 0.8}
        effects = {"beat_flash_intensity": 0.7, "motion_blur": 0.5}

        _create_beat_synced_loop(
            keyframes=keyframes,
            output_path=output,
            bpm=128.0,
            phrase=phrase,
            config=config,
            effects=effects,
        )

        assert output.exists()
        assert output.stat().st_size > 100


def test_resize_and_crop():
    """Test image resize and crop to target dimensions."""
    # Wide image
    wide = Image.new("RGB", (2000, 800), (255, 0, 0))
    result = _resize_and_crop(wide, 1920, 1080)
    assert result.size == (1920, 1080)

    # Tall image
    tall = Image.new("RGB", (800, 2000), (0, 255, 0))
    result = _resize_and_crop(tall, 1920, 1080)
    assert result.size == (1920, 1080)

    # Square image
    sq = Image.new("RGB", (1000, 1000), (0, 0, 255))
    result = _resize_and_crop(sq, 1920, 1080)
    assert result.size == (1920, 1080)


def test_auto_loop_beats():
    """Test auto loop duration selection."""
    assert _auto_loop_beats(174) == 16  # DnB
    assert _auto_loop_beats(128) == 8   # House
    assert _auto_loop_beats(140) == 8   # Trance
    assert _auto_loop_beats(90) == 8    # Slow


def test_beat_pulse():
    """Test beat pulse curve."""
    # At beat start: maximum
    assert _beat_pulse(0.0) > 0.9
    # At beat middle: much lower
    assert _beat_pulse(0.5) < 0.15
    # At beat end: near zero
    assert _beat_pulse(0.9) < 0.01


def test_beat_flash():
    """Test beat flash curve."""
    # At beat start: full flash
    assert _beat_flash(0.0) == 1.0
    # Just after flash window: zero
    assert _beat_flash(0.15) == 0.0
    # Mid-beat: zero
    assert _beat_flash(0.5) == 0.0
