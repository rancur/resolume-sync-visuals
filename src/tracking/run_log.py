"""
Structured JSON logging for generation runs.
Each run produces a JSONL file with timestamped events.
"""
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path.home() / ".rsv" / "logs"


class RunLogger:
    """Structured JSON logging for generation runs."""

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def start_run(self, command: str, args: dict) -> str:
        """Log run start. Returns log_id."""
        log_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        log_path = self._log_path(log_id)
        event = {
            "type": "run_start",
            "log_id": log_id,
            "timestamp": datetime.now().isoformat(),
            "command": command,
            "args": args,
        }
        self._append(log_path, event)
        return log_id

    def log_event(self, log_id: str, level: str, message: str, **data):
        """Append a structured event to the run log."""
        event = {
            "type": "event",
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            **data,
        }
        self._append(self._log_path(log_id), event)

    def log_track(self, log_id: str, track: str, status: str,
                  bpm: float, phrases: int, clips: int, cost: float,
                  mood: str = "", error: str = ""):
        """Log per-track result."""
        event = {
            "type": "track",
            "timestamp": datetime.now().isoformat(),
            "track": track,
            "status": status,
            "bpm": bpm,
            "phrases": phrases,
            "clips": clips,
            "cost": cost,
            "mood": mood,
            "error": error,
        }
        self._append(self._log_path(log_id), event)

    def end_run(self, log_id: str, summary: dict):
        """Log run completion."""
        event = {
            "type": "run_end",
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
        }
        self._append(self._log_path(log_id), event)

    def get_recent_runs(self, limit: int = 10) -> list[dict]:
        """List recent run logs with summary info."""
        log_files = sorted(self.log_dir.glob("run_*.jsonl"), reverse=True)
        runs = []
        for lf in log_files[:limit]:
            events = self._read_log(lf)
            if not events:
                continue
            start_event = events[0]
            end_event = None
            track_count = 0
            total_cost = 0.0
            for e in events:
                if e.get("type") == "run_end":
                    end_event = e
                if e.get("type") == "track":
                    track_count += 1
                    total_cost += e.get("cost", 0)

            log_id = start_event.get("log_id", lf.stem.replace("run_", ""))
            runs.append({
                "log_id": log_id,
                "command": start_event.get("command", ""),
                "started_at": start_event.get("timestamp", ""),
                "status": "completed" if end_event else "in_progress",
                "tracks": track_count,
                "total_cost": total_cost,
                "summary": end_event.get("summary", {}) if end_event else {},
            })
        return runs

    def get_run_log(self, log_id: str) -> list[dict]:
        """Read all events from a run."""
        log_path = self._log_path(log_id)
        if not log_path.exists():
            return []
        return self._read_log(log_path)

    def _log_path(self, log_id: str) -> Path:
        return self.log_dir / f"run_{log_id}.jsonl"

    def _append(self, path: Path, event: dict):
        with open(path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")

    @staticmethod
    def _read_log(path: Path) -> list[dict]:
        events = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return events
