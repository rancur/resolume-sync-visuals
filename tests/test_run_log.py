"""Tests for structured run logging."""
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

    def test_log_event(self):
        rl = self._make_logger()
        log_id = rl.start_run("generate", {})
        rl.log_event(log_id, "info", "Starting generation")
        rl.log_event(log_id, "warning", "Rate limited, retrying")

        events = rl.get_run_log(log_id)
        assert len(events) >= 3  # start + 2 events

    def test_log_track(self):
        rl = self._make_logger()
        log_id = rl.start_run("bulk", {})
        rl.log_track(log_id, "track1.flac", "completed", bpm=128.0,
                     phrases=6, clips=6, cost=0.50, mood="euphoric")

        events = rl.get_run_log(log_id)
        track_events = [e for e in events if e.get("type") == "track"]
        assert len(track_events) == 1
        assert track_events[0]["track"] == "track1.flac"

    def test_end_run(self):
        rl = self._make_logger()
        log_id = rl.start_run("generate", {})
        rl.end_run(log_id, {"total": 1, "cost": 0.50})

        events = rl.get_run_log(log_id)
        end_events = [e for e in events if e.get("type") == "run_end"]
        assert len(end_events) == 1

    def test_get_recent_runs(self):
        rl = self._make_logger()
        rl.start_run("generate", {"file": "a.flac"})
        rl.start_run("bulk", {"dir": "/music"})

        recent = rl.get_recent_runs(limit=10)
        assert len(recent) == 2

    def test_empty_log(self):
        rl = self._make_logger()
        recent = rl.get_recent_runs()
        assert recent == []
