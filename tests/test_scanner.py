"""Tests for the NAS music library scanner."""
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.scanner import (
    read_track_metadata,
    scan_library,
    read_engine_db,
    read_rekordbox_xml,
    read_bpm_from_tags,
)


def _make_flac_with_tags(bpm=140.0, title="FLAC Track", artist="DJ Test",
                         genre="House", key="Cm"):
    """Create a FLAC file with Vorbis comment tags."""
    from mutagen.flac import FLAC

    tmp = tempfile.NamedTemporaryFile(suffix=".flac", delete=False)
    tmp_path = tmp.name
    tmp.close()

    sr = 22050
    y = np.sin(2 * np.pi * 440 * np.arange(int(sr * 2.0)) / sr).astype(np.float32)
    sf.write(tmp_path, y, sr, format="FLAC")

    audio = FLAC(tmp_path)
    audio["title"] = title
    audio["artist"] = artist
    audio["genre"] = genre
    audio["bpm"] = str(bpm)
    audio["key"] = key
    audio.save()

    return tmp_path


def _make_wav_no_tags():
    """Create a plain WAV file with no tags."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    sr = 22050
    y = np.zeros(sr, dtype=np.float32)
    sf.write(tmp_path, y, sr)
    return tmp_path


class TestReadTrackMetadata:
    def test_reads_flac_tags(self):
        path = _make_flac_with_tags(bpm=174.0, title="Jungle Fire", artist="DJ Shadow",
                                    genre="DnB", key="Fm")
        try:
            meta = read_track_metadata(path)
            assert meta["title"] == "Jungle Fire"
            assert meta["artist"] == "DJ Shadow"
            assert meta["bpm"] == 174.0
            assert meta["genre"] == "DnB"
            assert meta["key"] == "Fm"
            assert meta["format"] == "FLAC"
            assert meta["size"] > 0
            assert meta["duration"] is not None and meta["duration"] > 0
        finally:
            os.unlink(path)

    def test_wav_no_tags_returns_none_fields(self):
        path = _make_wav_no_tags()
        try:
            meta = read_track_metadata(path)
            assert meta["path"] == str(Path(path).resolve())
            assert meta["format"] == "WAV"
            assert meta["size"] > 0
            # No tags available
            assert meta["bpm"] is None
            assert meta["genre"] is None
        finally:
            os.unlink(path)

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            read_track_metadata("/nonexistent/file.mp3")

    def test_returns_all_expected_keys(self):
        path = _make_flac_with_tags()
        try:
            meta = read_track_metadata(path)
            expected_keys = {"path", "title", "artist", "album", "bpm", "genre",
                             "key", "duration", "format", "size"}
            assert set(meta.keys()) == expected_keys
        finally:
            os.unlink(path)


class TestScanLibrary:
    def test_scans_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some FLAC files
            for i in range(3):
                path = os.path.join(tmpdir, f"track_{i}.flac")
                sr = 22050
                y = np.zeros(sr, dtype=np.float32)
                sf.write(path, y, sr, format="FLAC")

            results = scan_library(tmpdir)
            assert len(results) == 3
            for r in results:
                assert "path" in r
                assert "format" in r

    def test_scan_non_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # File in root
            sf.write(os.path.join(tmpdir, "root.flac"),
                     np.zeros(22050, dtype=np.float32), 22050, format="FLAC")
            # File in subdirectory
            subdir = os.path.join(tmpdir, "sub")
            os.makedirs(subdir)
            sf.write(os.path.join(subdir, "nested.flac"),
                     np.zeros(22050, dtype=np.float32), 22050, format="FLAC")

            # Recursive should find both
            results_recursive = scan_library(tmpdir, recursive=True)
            assert len(results_recursive) == 2

            # Non-recursive should find only root
            results_flat = scan_library(tmpdir, recursive=False)
            assert len(results_flat) == 1

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = scan_library(tmpdir)
            assert results == []

    def test_not_a_directory_raises(self):
        with pytest.raises(NotADirectoryError):
            scan_library("/nonexistent/path")


class TestReadBpmFromTags:
    def test_returns_bpm_from_tagged_file(self):
        path = _make_flac_with_tags(bpm=145.0)
        try:
            bpm = read_bpm_from_tags(path)
            assert bpm == 145.0
        finally:
            os.unlink(path)

    def test_returns_none_for_untagged_file(self):
        path = _make_wav_no_tags()
        try:
            bpm = read_bpm_from_tags(path)
            assert bpm is None
        finally:
            os.unlink(path)

    def test_returns_none_for_nonexistent(self):
        bpm = read_bpm_from_tags("/nonexistent/file.mp3")
        assert bpm is None


class TestReadEngineDb:
    def test_reads_engine_db(self):
        """Test reading from a mock Engine DJ SQLite database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            db_path = tmp.name

        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE Track (
                    path TEXT,
                    filename TEXT,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    genre TEXT,
                    bpmAnalyzed REAL,
                    keyText TEXT,
                    rating INTEGER,
                    length REAL
                )
            """)
            conn.execute("""
                INSERT INTO Track VALUES
                ('/music/track1.flac', 'track1.flac', 'Bass Drop', 'DJ Test',
                 'Album 1', 'DnB', 174.0, 'Am', 5, 360.0)
            """)
            conn.execute("""
                INSERT INTO Track VALUES
                ('/music/track2.mp3', 'track2.mp3', 'Chill Vibes', 'Producer X',
                 'Album 2', 'House', 124.0, 'Cm', 3, 240.0)
            """)
            conn.commit()
            conn.close()

            results = read_engine_db(db_path)
            assert len(results) == 2
            assert results[0]["title"] == "Bass Drop"
            assert results[0]["bpm"] == 174.0
            assert results[0]["key"] == "Am"
            assert results[0]["source"] == "engine_dj"
            assert results[1]["title"] == "Chill Vibes"
            assert results[1]["bpm"] == 124.0
        finally:
            os.unlink(db_path)

    def test_nonexistent_db_raises(self):
        with pytest.raises(FileNotFoundError):
            read_engine_db("/nonexistent/m.db")


class TestReadRekordboxXml:
    def test_reads_rekordbox_xml(self):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <DJ_PLAYLISTS Version="1.0.0">
            <PRODUCT Name="rekordbox" Version="6.0.0"/>
            <COLLECTION Entries="2">
                <TRACK TrackID="1" Name="Fire Track" Artist="DJ Blaze"
                       Album="Hot Beats" Genre="Techno" AverageBpm="130.00"
                       Tonality="Dm" TotalTime="300" Rating="5"
                       Location="file:///music/fire.mp3"/>
                <TRACK TrackID="2" Name="Ice Flow" Artist="Producer Cool"
                       Album="Cold Vibes" Genre="Ambient" AverageBpm="90.50"
                       Tonality="C" TotalTime="420" Rating="3"
                       Location="file:///music/ice.flac"/>
            </COLLECTION>
        </DJ_PLAYLISTS>"""

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as tmp:
            tmp.write(xml_content)
            xml_path = tmp.name

        try:
            results = read_rekordbox_xml(xml_path)
            assert len(results) == 2
            assert results[0]["title"] == "Fire Track"
            assert results[0]["artist"] == "DJ Blaze"
            assert results[0]["bpm"] == 130.0
            assert results[0]["key"] == "Dm"
            assert results[0]["source"] == "rekordbox"
            assert results[1]["bpm"] == 90.5
            assert results[1]["duration"] == 420.0
        finally:
            os.unlink(xml_path)

    def test_nonexistent_xml_raises(self):
        with pytest.raises(FileNotFoundError):
            read_rekordbox_xml("/nonexistent/library.xml")

    def test_empty_collection(self):
        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <DJ_PLAYLISTS Version="1.0.0">
            <COLLECTION Entries="0">
            </COLLECTION>
        </DJ_PLAYLISTS>"""

        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w") as tmp:
            tmp.write(xml_content)
            xml_path = tmp.name

        try:
            results = read_rekordbox_xml(xml_path)
            assert results == []
        finally:
            os.unlink(xml_path)
