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
        run_id = bp.start_run("/music/edm", "cyberpunk", "high", 5)
        assert run_id
        assert len(run_id) == 12

    def test_run_status_initial(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music/edm", "cyberpunk", "high", 5)
        status = bp.get_run_status(run_id)
        assert status["total"] == 5
        assert status["completed"] == 0
        assert status["failed"] == 0
        assert status["skipped"] == 0
        assert status["remaining"] == 5
        assert status["status"] == "in_progress"

    def test_mark_file_complete(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 3)
        bp.mark_file_complete(run_id, "/music/track1.flac", "/output/track1", cost=0.50, clips=8)
        status = bp.get_run_status(run_id)
        assert status["completed"] == 1
        assert status["remaining"] == 2
        assert status["total_cost"] == pytest.approx(0.50)
        assert status["total_clips"] == 8

    def test_mark_file_failed(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 3)
        bp.mark_file_failed(run_id, "/music/bad.flac", "Corrupted audio")
        status = bp.get_run_status(run_id)
        assert status["failed"] == 1
        assert status["remaining"] == 2

    def test_mark_file_skipped(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 3)
        bp.mark_file_skipped(run_id, "/music/done.flac", "already exists")
        status = bp.get_run_status(run_id)
        assert status["skipped"] == 1
        assert status["remaining"] == 2

    def test_complete_run(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 2)
        bp.mark_file_complete(run_id, "/music/a.flac", "/out/a", 0.10, 4)
        bp.mark_file_complete(run_id, "/music/b.flac", "/out/b", 0.20, 6)
        bp.complete_run(run_id)
        status = bp.get_run_status(run_id)
        assert status["status"] == "completed"
        assert status["completed"] == 2
        assert status["completed_at"] is not None

    def test_get_completed_files(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 3)
        bp.mark_file_complete(run_id, "/music/a.flac", "/out/a", 0.10, 4)
        bp.mark_file_skipped(run_id, "/music/b.flac", "exists")
        bp.mark_file_failed(run_id, "/music/c.flac", "error")
        done = bp.get_completed_files(run_id)
        assert "/music/a.flac" in done
        assert "/music/b.flac" in done
        assert "/music/c.flac" not in done

    def test_get_incomplete_files(self):
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 3)
        bp.mark_file_complete(run_id, "/music/a.flac", "/out/a", 0.5, 6)
        bp.mark_file_failed(run_id, "/music/b.flac", "error")
        # c.flac never processed

        incomplete = bp.get_incomplete_files(run_id)
        # Should include the failed one (for retry) but not the completed one
        assert "/music/b.flac" in incomplete
        assert "/music/a.flac" not in incomplete

    def test_get_latest_run(self):
        bp = self._make_progress()
        norm_dir = str(Path("/tmp/test_music_latest").resolve())
        run1 = bp.start_run(norm_dir, "abstract", "high", 5)
        run2 = bp.start_run(norm_dir, "cyberpunk", "high", 5)
        latest = bp.get_latest_run(norm_dir)
        assert latest == run2

    def test_get_latest_run_completed_not_returned(self):
        bp = self._make_progress()
        norm_dir = str(Path("/tmp/test_music_completed").resolve())
        run_id = bp.start_run(norm_dir, "abstract", "high", 1)
        bp.mark_file_complete(run_id, "/music/a.flac", "/out/a", 0.10, 4)
        bp.complete_run(run_id)
        # Completed run should not be returned as "latest in_progress"
        latest = bp.get_latest_run(norm_dir)
        assert latest is None

    def test_get_latest_run_no_runs(self):
        bp = self._make_progress()
        latest = bp.get_latest_run("/nonexistent/dir")
        assert latest is None

    def test_get_run_status_nonexistent(self):
        bp = self._make_progress()
        status = bp.get_run_status("nonexistent_id")
        assert status == {}

    def test_resume_lifecycle(self):
        """Full resume scenario: start run, process some, resume with remaining."""
        bp = self._make_progress()
        norm_dir = str(Path("/tmp/resume_test").resolve())
        run_id = bp.start_run(norm_dir, "abstract", "high", 4)

        # Process first two
        bp.mark_file_complete(run_id, "/music/a.flac", "/out/a", 0.10, 3)
        bp.mark_file_complete(run_id, "/music/b.flac", "/out/b", 0.20, 5)
        bp.mark_file_failed(run_id, "/music/c.flac", "timeout")

        status = bp.get_run_status(run_id)
        assert status["completed"] == 2
        assert status["failed"] == 1
        assert status["remaining"] == 1  # d.flac not touched

        done = bp.get_completed_files(run_id)
        assert len(done) == 2

        # Process remaining and retry failed
        bp.mark_file_complete(run_id, "/music/d.flac", "/out/d", 0.15, 4)
        bp.mark_file_complete(run_id, "/music/c.flac", "/out/c", 0.25, 6)
        bp.complete_run(run_id)

        final = bp.get_run_status(run_id)
        assert final["status"] == "completed"
        assert final["completed"] == 4  # a, b, c (retried), d
        assert final["total_clips"] == 18

    def test_upsert_file_status(self):
        """Re-marking a file updates rather than duplicating."""
        bp = self._make_progress()
        run_id = bp.start_run("/music", "abstract", "high", 2)
        bp.mark_file_failed(run_id, "/music/a.flac", "timeout")
        status = bp.get_run_status(run_id)
        assert status["failed"] == 1

        # Retry succeeds -- should update, not duplicate
        bp.mark_file_complete(run_id, "/music/a.flac", "/out/a", 0.30, 5)
        status = bp.get_run_status(run_id)
        assert status["completed"] == 1
        assert status["failed"] == 0

    def test_multiple_runs_same_directory(self):
        bp = self._make_progress()
        norm_dir = str(Path("/tmp/multi_run").resolve())
        run1 = bp.start_run(norm_dir, "abstract", "high", 3)
        bp.mark_file_complete(run1, "/music/a.flac", "/out/a", 0.10, 4)
        bp.complete_run(run1)

        run2 = bp.start_run(norm_dir, "cyberpunk", "standard", 3)
        latest = bp.get_latest_run(norm_dir)
        assert latest == run2  # Only in-progress run returned
