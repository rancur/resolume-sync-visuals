"""Tests for Denon Engine DJ integration."""
import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.denon.engine_db import read_engine_library, read_track_info, read_crates, find_engine_db
from src.denon.stagelinq import StagelinQListener, DeckState, StagelinQDevice, STAGELINQ_MAGIC


def _create_test_engine_db(db_path: Path):
    """Create a minimal Engine DJ database for testing."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE Track (
            id INTEGER PRIMARY KEY,
            path TEXT,
            filename TEXT,
            title TEXT,
            artist TEXT,
            album TEXT,
            genre TEXT,
            bpmAnalyzed REAL,
            keyText TEXT,
            length REAL,
            rating INTEGER,
            comment TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE Crate (
            id INTEGER PRIMARY KEY,
            title TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE CrateTrackList (
            crateId INTEGER,
            trackId INTEGER
        )
    """)

    # Insert test tracks
    conn.execute("""
        INSERT INTO Track (id, path, filename, title, artist, album, genre, bpmAnalyzed, keyText, length)
        VALUES (1, '/music/house_track.flac', 'house_track.flac', 'Deep House Groove', 'DJ Test', 'Test Album', 'House', 128.0, '8A', 240.5)
    """)
    conn.execute("""
        INSERT INTO Track (id, path, filename, title, artist, album, genre, bpmAnalyzed, keyText, length)
        VALUES (2, '/music/dnb_track.flac', 'dnb_track.flac', 'Jump Up', 'MC Test', 'DnB Album', 'Drum & Bass', 174.0, '3B', 180.0)
    """)
    conn.execute("""
        INSERT INTO Track (id, path, filename, title, artist, album, genre, bpmAnalyzed, keyText, length)
        VALUES (3, '/music/trance_track.mp3', 'trance_track.mp3', 'Euphoria', 'Trance DJ', '', 'Trance', 140.0, '11B', 360.0)
    """)

    # Insert crates
    conn.execute("INSERT INTO Crate (id, title) VALUES (1, 'Main Set')")
    conn.execute("INSERT INTO Crate (id, title) VALUES (2, 'Warm Up')")
    conn.execute("INSERT INTO CrateTrackList (crateId, trackId) VALUES (1, 1)")
    conn.execute("INSERT INTO CrateTrackList (crateId, trackId) VALUES (1, 2)")
    conn.execute("INSERT INTO CrateTrackList (crateId, trackId) VALUES (2, 3)")

    conn.commit()
    conn.close()


class TestEngineDB:
    def test_read_engine_library(self, tmp_path):
        db_path = tmp_path / "m.db"
        _create_test_engine_db(db_path)

        tracks = read_engine_library(db_path)
        assert len(tracks) == 3

        house = next(t for t in tracks if t["title"] == "Deep House Groove")
        assert house["bpm"] == 128.0
        assert house["key"] == "8A"
        assert house["artist"] == "DJ Test"
        assert house["genre"] == "House"

    def test_read_track_info(self, tmp_path):
        db_path = tmp_path / "m.db"
        _create_test_engine_db(db_path)

        track = read_track_info(db_path, "dnb_track.flac")
        assert track is not None
        assert track["bpm"] == 174.0
        assert track["title"] == "Jump Up"

    def test_read_track_info_not_found(self, tmp_path):
        db_path = tmp_path / "m.db"
        _create_test_engine_db(db_path)

        track = read_track_info(db_path, "nonexistent.flac")
        assert track is None

    def test_read_crates(self, tmp_path):
        db_path = tmp_path / "m.db"
        _create_test_engine_db(db_path)

        crates = read_crates(db_path)
        assert len(crates) == 2

        main_set = next(c for c in crates if c["title"] == "Main Set")
        assert main_set["track_count"] == 2
        assert 1 in main_set["track_ids"]
        assert 2 in main_set["track_ids"]

    def test_missing_db(self):
        with pytest.raises(FileNotFoundError):
            read_engine_library("/nonexistent/m.db")

    def test_find_engine_db_explicit(self, tmp_path):
        db_path = tmp_path / "Engine Library" / "m.db"
        db_path.parent.mkdir(parents=True)
        db_path.write_bytes(b"")

        result = find_engine_db([str(tmp_path)])
        assert result == db_path


class TestStagelinQ:
    def test_listener_create(self):
        listener = StagelinQListener()
        assert listener.devices == []
        assert listener.deck_states == {}

    def test_simulate_deck_update(self):
        listener = StagelinQListener()
        listener.simulate_deck_update(1, track_name="Test Track", bpm=128.0, playing=True)

        state = listener.get_deck_state(1)
        assert state is not None
        assert state.track_name == "Test Track"
        assert state.bpm == 128.0
        assert state.playing is True

    def test_track_change_callback(self):
        listener = StagelinQListener()
        changes = []
        listener.on_track_change = lambda deck_id, state: changes.append((deck_id, state.track_name))

        listener.simulate_deck_update(1, track_name="Track A", bpm=128.0)
        listener.simulate_deck_update(1, track_name="Track B", bpm=140.0)

        assert len(changes) == 2
        assert changes[0] == (1, "Track A")
        assert changes[1] == (1, "Track B")

    def test_bpm_change_callback(self):
        listener = StagelinQListener()
        bpm_changes = []
        listener.on_bpm_change = lambda deck_id, bpm: bpm_changes.append((deck_id, bpm))

        listener.simulate_deck_update(1, bpm=128.0)
        listener.simulate_deck_update(1, bpm=130.0)

        assert len(bpm_changes) == 2

    def test_get_master_bpm(self):
        listener = StagelinQListener()
        listener.simulate_deck_update(1, bpm=128.0, master_bpm=128.0)
        listener.simulate_deck_update(2, bpm=140.0)

        assert listener.get_master_bpm() == 128.0

    def test_discovery_packet_parse(self):
        listener = StagelinQListener()
        # Build a fake discovery packet
        packet = STAGELINQ_MAGIC + b"\x00\x50"  # port 80
        packet += b"SC6000\x00Engine DJ\x001.0.0\x00"

        device = listener._parse_discovery(packet, "192.168.1.100")
        assert device is not None
        assert device.ip == "192.168.1.100"
        assert device.name == "SC6000"

    def test_invalid_discovery_packet(self):
        listener = StagelinQListener()
        device = listener._parse_discovery(b"garbage", "1.2.3.4")
        assert device is None

    def test_deck_state_defaults(self):
        state = DeckState()
        assert state.bpm == 0.0
        assert state.playing is False
        assert state.track_name == ""
