"""Tests for montage builder (src/composer/montage.py)."""
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.composer.montage import create_montage


class TestCreateMontage:
    def test_empty_clips_returns_output_path(self, tmp_path):
        output = tmp_path / "montage.mp4"
        result = create_montage([], "/tmp/audio.wav", output, {})
        assert result == output

    def test_no_valid_clip_files(self, tmp_path):
        output = tmp_path / "montage.mp4"
        clips = [{"path": "/nonexistent/clip.mp4"}]
        result = create_montage(clips, "/tmp/audio.wav", output, {})
        assert result == output

    def test_creates_parent_directory(self, tmp_path):
        output = tmp_path / "subdir" / "montage.mp4"
        create_montage([], "/tmp/audio.wav", output, {})
        assert output.parent.exists()
