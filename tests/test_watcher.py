"""Tests for the watch mode module."""
import tempfile
import time
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from src.watcher import (
    MusicFileHandler,
    MUSIC_EXTENSIONS,
    _sanitize_name,
    _load_style,
)


def _make_audio(path: Path, duration: float = 5.0, sr: int = 22050):
    """Write a short synthetic audio file."""
    n = int(duration * sr)
    y = 0.3 * np.sin(2 * np.pi * 440 * np.arange(n) / sr)
    sf.write(str(path), y, sr)


class TestMusicFileHandler:
    """Tests for the filesystem event handler."""

    def test_queues_music_files(self):
        """New music files get added to the processing queue."""
        queue = Queue()
        registry = MagicMock()
        handler = MusicFileHandler(queue, registry, style="abstract")

        # Simulate file creation events for each supported extension
        for ext in MUSIC_EXTENSIONS:
            event = MagicMock()
            event.is_directory = False
            event.src_path = f"/tmp/test_track{ext}"
            handler.on_created(event)

        assert queue.qsize() == len(MUSIC_EXTENSIONS)

    def test_ignores_non_music_files(self):
        """Non-music files are not queued."""
        queue = Queue()
        registry = MagicMock()
        handler = MusicFileHandler(queue, registry, style="abstract")

        for ext in [".txt", ".jpg", ".py", ".yaml", ".json", ".mp4"]:
            event = MagicMock()
            event.is_directory = False
            event.src_path = f"/tmp/test{ext}"
            handler.on_created(event)

        assert queue.qsize() == 0

    def test_ignores_directories(self):
        """Directory creation events are ignored."""
        queue = Queue()
        registry = MagicMock()
        handler = MusicFileHandler(queue, registry, style="abstract")

        event = MagicMock()
        event.is_directory = True
        event.src_path = "/tmp/some_dir"
        handler.on_created(event)

        assert queue.qsize() == 0


class TestSanitizeName:
    def test_replaces_special_chars(self):
        assert _sanitize_name("track/one") == "track_one"
        assert _sanitize_name('track:"remix"') == "track__remix_"

    def test_strips_dots(self):
        assert _sanitize_name(".hidden.") == "hidden"

    def test_normal_name_unchanged(self):
        assert _sanitize_name("my_track_01") == "my_track_01"


class TestLoadStyle:
    def test_loads_existing_style(self):
        config = _load_style("abstract")
        assert isinstance(config, dict)
        assert "name" in config or "description" in config or "colors" in config

    def test_raises_for_missing_style(self):
        with pytest.raises(FileNotFoundError):
            _load_style("nonexistent_style_xyz")


class TestMusicExtensions:
    def test_all_expected_extensions(self):
        expected = {".flac", ".mp3", ".wav", ".aif", ".aiff", ".ogg"}
        assert MUSIC_EXTENSIONS == expected
