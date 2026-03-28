"""Tests for concurrent bulk processing."""
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.bulk_processor import find_music_files, BulkResult, _sanitize, _load_style_config


def _make_test_audio(path: Path, duration: float = 5.0, sr: int = 22050):
    """Create a minimal test audio file."""
    y = np.random.randn(int(duration * sr)).astype(np.float32) * 0.1
    sf.write(str(path), y, sr)


class TestFindMusicFiles:
    def test_finds_music_files(self, tmp_path):
        (tmp_path / "song.mp3").write_bytes(b"\x00" * 100)
        (tmp_path / "song.flac").write_bytes(b"\x00" * 100)
        (tmp_path / "song.wav").write_bytes(b"\x00" * 100)
        (tmp_path / "readme.txt").write_bytes(b"not music")

        files = find_music_files(tmp_path)
        assert len(files) == 3
        assert all(f.suffix in {".mp3", ".flac", ".wav"} for f in files)

    def test_recursive_search(self, tmp_path):
        (tmp_path / "root.mp3").write_bytes(b"\x00")
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (subdir / "nested.mp3").write_bytes(b"\x00")

        assert len(find_music_files(tmp_path, recursive=True)) == 2
        assert len(find_music_files(tmp_path, recursive=False)) == 1

    def test_empty_directory(self, tmp_path):
        assert find_music_files(tmp_path) == []

    def test_nonexistent_directory(self):
        with pytest.raises(NotADirectoryError):
            find_music_files("/nonexistent/path")

    def test_sorted_results(self, tmp_path):
        (tmp_path / "b_song.wav").write_bytes(b"\x00")
        (tmp_path / "a_song.wav").write_bytes(b"\x00")
        files = find_music_files(tmp_path)
        assert files[0].name == "a_song.wav"


class TestSanitize:
    def test_replaces_special_chars(self):
        assert _sanitize("track/name:2") == "track_name_2"

    def test_strips_dots(self):
        assert _sanitize(".hidden.") == "hidden"

    def test_normal_name(self):
        assert _sanitize("normal_name") == "normal_name"


class TestLoadStyleConfig:
    def test_loads_existing_style(self):
        config = _load_style_config("abstract")
        assert "prompts" in config
        assert "base" in config["prompts"]

    def test_auto_returns_default(self):
        config = _load_style_config("auto")
        assert "prompts" in config

    def test_missing_style_returns_default(self):
        config = _load_style_config("nonexistent_style_xyz")
        assert "prompts" in config


class TestBulkResult:
    def test_defaults(self):
        result = BulkResult()
        assert result.total == 0
        assert result.completed == 0
        assert result.errors == []

    def test_with_values(self):
        result = BulkResult(total=10, completed=8, failed=2, total_cost=1.50)
        assert result.total == 10
        assert result.total_cost == 1.50
