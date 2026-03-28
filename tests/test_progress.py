"""Tests for bulk progress persistence."""
import tempfile
from pathlib import Path

import pytest

from src.tracking.progress import BulkProgress


class TestBulkProgress:
    def _make_progress(self):
        return BulkProgress(db_path=Path(tempfile.mktemp(suffix=".db")))

    def test_start_run(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 10)
        assert run_id
        assert len(run_id) > 0

    def test_mark_complete(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 3)
        bp.mark_file_complete(run_id, "/music/track1.flac", "/output/track1", cost=0.50, clips=6)

        status = bp.get_run_status(run_id)
        assert status["completed"] == 1
        assert status["total"] == 3

    def test_mark_failed(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 3)
        bp.mark_file_failed(run_id, "/music/bad.flac", "Corrupted audio")

        status = bp.get_run_status(run_id)
        assert status["failed"] == 1

    def test_mark_skipped(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 3)
        bp.mark_file_skipped(run_id, "/music/done.flac", "already exists")

        status = bp.get_run_status(run_id)
        assert status["skipped"] == 1

    def test_get_incomplete_files(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 3)
        bp.mark_file_complete(run_id, "/music/a.flac", "/out/a", 0.5, 6)
        bp.mark_file_failed(run_id, "/music/b.flac", "error")
        # c.flac never processed

        incomplete = bp.get_incomplete_files(run_id)
        # Should include the failed one (for retry) but not the completed one
        assert "/music/a.flac" not in incomplete

    def test_complete_run(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 1)
        bp.mark_file_complete(run_id, "/music/a.flac", "/out/a", 0.5, 6)
        bp.complete_run(run_id)

        status = bp.get_run_status(run_id)
        assert status["completed"] == 1

    def test_get_latest_run(self):
        bp = self._make_progress()
        run1 = bp.start_run("/music", "abstract", "high", 5)
        run2 = bp.start_run("/music", "laser", "standard", 5)

        latest = bp.get_latest_run("/music")
        assert latest == run2
