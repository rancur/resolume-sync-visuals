"""
Log viewer endpoints — browse generation run logs.
"""
from fastapi import APIRouter, HTTPException, Query

from src.tracking import RunLogger

from ..config import get_settings

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _logger() -> RunLogger:
    from pathlib import Path
    settings = get_settings()
    return RunLogger(log_dir=Path(settings.db_path) / "logs")


@router.get("/runs")
def list_runs(limit: int = Query(20, ge=1, le=100)):
    rl = _logger()
    return {"runs": rl.get_recent_runs(limit=limit)}


@router.get("/runs/{log_id}")
def get_run(log_id: str):
    rl = _logger()
    events = rl.get_run_log(log_id)
    if not events:
        raise HTTPException(404, "Run log not found")
    return {"log_id": log_id, "events": events}
