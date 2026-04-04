"""Tests for structured run logging."""
import json
import tempfile
from pathlib import Path

import pytest

from src.tracking.run_log import RunLogger


class TestRunLogger:
    def _make_logger(self):
        return RunLogger(log_dir=Path(tempfile.mkdtemp()))

    def test_start_run(self):
        rl = self._make_logger()
        log_id = rl.start_run("generate", {"file": "track.flac", "style": "abstract"})
        assert log_id
        assert len(log_id) > 0

    def test_start_run_creates_file(self):
        rl = self._make_logger()
        log_id = rl.start_run("bulk", {"directory": "/music"})
        log_path = rl._log_path(log_id)
        assert log_path.exists()

    def test_log_event(self):
        rl = self._make_logger()
        log_id = rl.start_run("generate", {})
        rl.log_event(log_id, "info", "Starting generation")
        rl.log_event(log_id, "warning", "Rate limited, retrying")

        events = rl.get_run_log(log_id)
        assert len(events) == 3  # start + 2 events
        assert events[1]["level"] == "info"
        assert events[2]["level"] == "warning"

    def test_log_event_with_extra_data(self):
        rl = self._make_logger()
        log_id = rl.start_run("generate", {})
        rl.log_event(log_id, "info", "Phrase generated", phrase_idx=3, cost=0.08)

        events = rl.get_run_log(log_id)
        data_event = events[1]
        assert data_event["phrase_idx"] == 3
        assert data_event["cost"] == 0.08

    def test_log_track(self):
        rl = self._make_logger()
        log_id = rl.start_run("bulk", {})
        rl.log_track(log_id, "track1.flac", "completed", bpm=128.0,
                     phrases=6, clips=6, cost=0.50, mood="euphoric")

        events = rl.get_run_log(log_id)
        track_events = [e for e in events if e.get("type") == "track"]
        assert len(track_events) == 1
        assert track_events[0]["track"] == "track1.flac"
        assert track_events[0]["bpm"] == 128.0
        assert track_events[0]["cost"] == 0.50
        assert track_events[0]["mood"] == "euphoric"

    def test_log_track_failed(self):
        rl = self._make_logger()
        log_id = rl.start_run("bulk", {})
        rl.log_track(log_id, "bad.flac", "failed", bpm=0, phrases=0,
                     clips=0, cost=0, error="Corrupted file")

        events = rl.get_run_log(log_id)
        track_events = [e for e in events if e.get("type") == "track"]
        assert track_events[0]["status"] == "failed"
        assert track_events[0]["error"] == "Corrupted file"

    def test_end_run(self):
        rl = self._make_logger()
        log_id = rl.start_run("generate", {})
        rl.end_run(log_id, {"total": 1, "cost": 0.50})

        events = rl.get_run_log(log_id)
        end_events = [e for e in events if e.get("type") == "run_end"]
        assert len(end_events) == 1
        assert end_events[0]["summary"]["total"] == 1

    def test_get_recent_runs(self):
        rl = self._make_logger()
        id1 = rl.start_run("generate", {"file": "a.flac"})
        rl.log_track(id1, "a.flac", "completed", bpm=128, phrases=4,
                     clips=4, cost=0.32)
        rl.end_run(id1, {"total": 1})

        id2 = rl.start_run("bulk", {"dir": "/music"})

        recent = rl.get_recent_runs(limit=10)
        assert len(recent) == 2
        # Both runs should be present
        log_ids = {r["log_id"] for r in recent}
        assert id1 in log_ids
        assert id2 in log_ids

    def test_recent_runs_shows_track_count_and_cost(self):
        rl = self._make_logger()
        log_id = rl.start_run("bulk", {})
        rl.log_track(log_id, "a.flac", "completed", bpm=128, phrases=4,
                     clips=4, cost=0.32)
        rl.log_track(log_id, "b.flac", "completed", bpm=140, phrases=6,
                     clips=6, cost=0.48)
        rl.end_run(log_id, {"total": 2})

        recent = rl.get_recent_runs()
        assert recent[0]["tracks"] == 2
        assert recent[0]["total_cost"] == pytest.approx(0.80)
        assert recent[0]["status"] == "completed"

    def test_recent_runs_in_progress_status(self):
        rl = self._make_logger()
        log_id = rl.start_run("bulk", {})
        rl.log_track(log_id, "a.flac", "completed", bpm=128, phrases=4,
                     clips=4, cost=0.32)
        # No end_run call

        recent = rl.get_recent_runs()
        assert recent[0]["status"] == "in_progress"

    def test_get_run_log_nonexistent(self):
        rl = self._make_logger()
        events = rl.get_run_log("nonexistent_id")
        assert events == []

    def test_empty_log_dir(self):
        rl = self._make_logger()
        recent = rl.get_recent_runs()
        assert recent == []

    def test_recent_runs_limit(self):
        rl = self._make_logger()
        for i in range(5):
            rl.start_run(f"cmd_{i}", {})

        recent = rl.get_recent_runs(limit=3)
        assert len(recent) == 3

    def test_jsonl_format(self):
        """Verify each line in the log file is valid JSON."""
        rl = self._make_logger()
        log_id = rl.start_run("generate", {"file": "test.flac"})
        rl.log_event(log_id, "info", "hello")
        rl.end_run(log_id, {"done": True})

        log_path = rl._log_path(log_id)
        with open(log_path) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 3
        for line in lines:
            parsed = json.loads(line)
            assert "timestamp" in parsed
