"""Tests for version tracking and rollback."""
import json
from pathlib import Path

import pytest

from src.tracking.versions import (
    DEFAULT_MAX_VERSIONS,
    VersionHistory,
    VersionTracker,
    VideoVersion,
)


@pytest.fixture
def tracker(tmp_path):
    return VersionTracker(registry_dir=tmp_path / "versions")


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "video.mov"
    f.write_bytes(b"\x00" * 1000)
    return f


# ── VideoVersion ─────────────────────────────────────────────────────

class TestVideoVersion:
    def test_to_dict(self):
        v = VideoVersion(version=1, track_title="Test", created_at="2026-01-01")
        d = v.to_dict()
        assert d["version"] == 1
        assert d["track_title"] == "Test"

    def test_from_dict(self):
        d = {"version": 2, "track_title": "Song", "created_at": "2026-01-01", "model": "kling"}
        v = VideoVersion.from_dict(d)
        assert v.version == 2
        assert v.model == "kling"

    def test_from_dict_ignores_extra_keys(self):
        d = {"version": 1, "track_title": "T", "created_at": "now", "unknown_field": "x"}
        v = VideoVersion.from_dict(d)
        assert v.version == 1


# ── VersionHistory ───────────────────────────────────────────────────

class TestVersionHistory:
    def test_latest_empty(self):
        h = VersionHistory(track_title="T")
        assert h.latest is None

    def test_latest_returns_current(self):
        h = VersionHistory(track_title="T", current_version=2, versions=[
            VideoVersion(version=1, track_title="T", created_at="a"),
            VideoVersion(version=2, track_title="T", created_at="b"),
        ])
        assert h.latest.version == 2

    def test_to_dict(self):
        h = VersionHistory(track_title="T", versions=[
            VideoVersion(version=1, track_title="T", created_at="a"),
        ], current_version=1)
        d = h.to_dict()
        assert d["total_versions"] == 1
        assert d["current_version"] == 1


# ── VersionTracker.add_version ───────────────────────────────────────

class TestAddVersion:
    def test_first_version(self, tracker):
        v = tracker.add_version("My Track", model="kling")
        assert v.version == 1
        assert v.track_title == "My Track"

    def test_increments_version(self, tracker):
        tracker.add_version("T", model="v1")
        v2 = tracker.add_version("T", model="v2")
        assert v2.version == 2

    def test_sets_current(self, tracker):
        tracker.add_version("T")
        tracker.add_version("T")
        h = tracker.get_history("T")
        assert h.current_version == 2

    def test_persists_to_disk(self, tracker):
        tracker.add_version("T", model="kling")
        # Create a new tracker pointing to same dir
        tracker2 = VersionTracker(registry_dir=tracker.registry_dir)
        h = tracker2.get_history("T")
        assert len(h.versions) == 1
        assert h.versions[0].model == "kling"

    def test_stores_metadata(self, tracker):
        v = tracker.add_version(
            "T",
            model="kling-v2",
            brand="example",
            quality_score=85,
            resolution="1920x1080",
        )
        assert v.model == "kling-v2"
        assert v.brand == "example"
        assert v.quality_score == 85


# ── Auto-cleanup ─────────────────────────────────────────────────────

class TestAutoCleanup:
    def test_enforces_max_versions(self, tracker, sample_file):
        for i in range(DEFAULT_MAX_VERSIONS + 2):
            tracker.add_version("T", file_path=str(sample_file))
        h = tracker.get_history("T")
        assert len(h.versions) <= DEFAULT_MAX_VERSIONS

    def test_keeps_current_version(self, tracker):
        for i in range(5):
            tracker.add_version("T")
        h = tracker.get_history("T")
        assert any(v.version == h.current_version for v in h.versions)


# ── Rollback ─────────────────────────────────────────────────────────

class TestRollback:
    def test_rollback_to_older(self, tracker):
        tracker.add_version("T", model="v1")
        tracker.add_version("T", model="v2")
        result = tracker.rollback("T", version=1)
        assert result is not None
        assert result.version == 1
        h = tracker.get_history("T")
        assert h.current_version == 1

    def test_rollback_nonexistent_version(self, tracker):
        tracker.add_version("T")
        result = tracker.rollback("T", version=99)
        assert result is None

    def test_rollback_nonexistent_track(self, tracker):
        result = tracker.rollback("NoSuchTrack", version=1)
        assert result is None


# ── List versions ────────────────────────────────────────────────────

class TestListVersions:
    def test_empty(self, tracker):
        assert tracker.list_versions("T") == []

    def test_with_current_marker(self, tracker):
        tracker.add_version("T")
        tracker.add_version("T")
        versions = tracker.list_versions("T")
        assert len(versions) == 2
        current = [v for v in versions if v["is_current"]]
        assert len(current) == 1
        assert current[0]["version"] == 2


# ── Delete version ───────────────────────────────────────────────────

class TestDeleteVersion:
    def test_delete_non_current(self, tracker):
        tracker.add_version("T")
        tracker.add_version("T")
        assert tracker.delete_version("T", version=1)
        h = tracker.get_history("T")
        assert len(h.versions) == 1

    def test_cannot_delete_current(self, tracker):
        tracker.add_version("T")
        assert not tracker.delete_version("T", version=1)

    def test_delete_nonexistent(self, tracker):
        tracker.add_version("T")
        assert not tracker.delete_version("T", version=99)


# ── Get all tracks ───────────────────────────────────────────────────

class TestGetAllTracks:
    def test_empty(self, tracker):
        assert tracker.get_all_tracks() == []

    def test_lists_all(self, tracker):
        tracker.add_version("Track A")
        tracker.add_version("Track B")
        tracks = tracker.get_all_tracks()
        assert "Track A" in tracks
        assert "Track B" in tracks

    def test_sorted(self, tracker):
        tracker.add_version("Zulu")
        tracker.add_version("Alpha")
        tracks = tracker.get_all_tracks()
        assert tracks == sorted(tracks)


# ── Disk usage ───────────────────────────────────────────────────────

class TestDiskUsage:
    def test_zero_when_empty(self, tracker):
        assert tracker.total_disk_usage() == 0

    def test_counts_file_sizes(self, tracker):
        tracker.add_version("T", file_size=1000)
        tracker.add_version("T", file_size=2000)
        assert tracker.total_disk_usage() == 3000
