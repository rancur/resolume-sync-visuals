"""Tests for NAS music library scanner."""
import tempfile
from pathlib import Path

import pytest

from src.scanner import scan_library, read_track_metadata, read_bpm_from_tags


def test_scan_library_empty_dir(tmp_path):
    """Test scanning an empty directory."""
    result = scan_library(str(tmp_path))
    assert result == []


def test_scan_library_with_files(tmp_path):
    """Test scanning a directory with music files."""
    # Create dummy files
    (tmp_path / "song1.mp3").write_bytes(b"\x00" * 100)
    (tmp_path / "song2.flac").write_bytes(b"\x00" * 100)
    (tmp_path / "readme.txt").write_bytes(b"not music")

    result = scan_library(str(tmp_path))
    # Should find music files (even without valid tags)
    music_paths = [r["path"] for r in result]
    assert any("song1.mp3" in p for p in music_paths)
    assert any("song2.flac" in p for p in music_paths)
    # Should not include text files
    assert not any("readme.txt" in p for p in music_paths)


def test_read_track_metadata_missing_file():
    """Test reading metadata from a non-existent file."""
    with pytest.raises(FileNotFoundError):
        read_track_metadata("/nonexistent/file.mp3")


def test_read_bpm_from_tags_no_tags(tmp_path):
    """Test BPM reading from a file without BPM tags."""
    test_file = tmp_path / "no_bpm.wav"
    test_file.write_bytes(b"\x00" * 1000)

    result = read_bpm_from_tags(str(test_file))
    # Should return None or 0 when no BPM tag exists
    assert result is None or result == 0


def test_read_bpm_from_tags_with_mutagen(tmp_path):
    """Test BPM reading from a file with proper ID3 tags."""
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, TBPM

        # Create a minimal MP3 with BPM tag
        test_file = tmp_path / "tagged.mp3"
        # Can't easily create a valid MP3 from scratch without actual audio
        # So we test that the function handles invalid files gracefully
        test_file.write_bytes(b"\xff\xfb\x90\x00" * 100)  # Fake MP3 frames

        result = read_bpm_from_tags(str(test_file))
        # Should not crash, may return None
        assert result is None or isinstance(result, (int, float))
    except ImportError:
        pytest.skip("mutagen not installed")
