"""
Budget and cost tracking endpoints.

Serves per-track costs, averages, recent generation history,
and bulk cost estimation for the financial dashboard.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from src.tracking import CostTracker

from ..config import get_settings

router = APIRouter(prefix="/api/budget", tags=["budget"])


def _tracker() -> CostTracker:
    settings = get_settings()
    from pathlib import Path
    return CostTracker(db_path=Path(settings.db_path) / "costs.db")


@router.get("/summary")
def budget_summary():
    t = _tracker()
    total_cost = t.get_total_cost()
    total_calls = t.get_total_calls()
    cache_rate = t.get_cache_hit_rate()
    by_day = t.get_cost_by_day(days=30)

    # Compute today/week/month costs
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    today_cost = t.get_total_cost(since=today_start)
    week_cost = t.get_total_cost(since=week_start)
    month_cost = t.get_total_cost(since=month_start)

    return {
        "total_cost": total_cost,
        "today_cost": today_cost,
        "week_cost": week_cost,
        "month_cost": month_cost,
        "total_api_calls": total_calls,
        "cache_hit_rate": cache_rate,
        "daily_costs": by_day,
    }


@router.get("/per-track")
def budget_per_track():
    """Cost breakdown per track with averages."""
    t = _tracker()
    tracks = t.get_cost_by_track()
    total_tracks = len(tracks)
    total_cost = sum(tr.get("total_cost", 0) for tr in tracks)
    avg_cost = total_cost / total_tracks if total_tracks > 0 else 0

    return {
        "tracks": tracks,
        "total_tracks": total_tracks,
        "total_cost": round(total_cost, 4),
        "avg_cost_per_track": round(avg_cost, 4),
    }


@router.get("/by-track")
def budget_by_track():
    t = _tracker()
    return {"tracks": t.get_cost_by_track()}


@router.get("/by-model")
def budget_by_model():
    """Cost breakdown by style (which maps to model usage)."""
    t = _tracker()
    return {"models": t.get_cost_by_style()}


@router.get("/recent")
def budget_recent(limit: int = Query(20, ge=1, le=100)):
    """Recent generation history with individual costs."""
    t = _tracker()
    calls = t.get_recent_calls(limit=limit)
    return {"generations": calls}


@router.get("/estimate")
def budget_estimate(tracks: int = Query(1, ge=1, le=1000)):
    """Estimate cost for generating N tracks based on historical average."""
    t = _tracker()
    by_track = t.get_cost_by_track()
    total_tracks = len(by_track)
    total_cost = sum(tr.get("total_cost", 0) for tr in by_track)
    avg_cost = total_cost / total_tracks if total_tracks > 0 else 0.25  # fallback estimate

    return {
        "requested_tracks": tracks,
        "avg_cost_per_track": round(avg_cost, 4),
        "estimated_total": round(avg_cost * tracks, 2),
        "based_on_tracks": total_tracks,
    }


@router.get("/projection")
def budget_projection(
    days: int = Query(30, ge=1, le=365),
):
    """Project future costs based on recent spending rate."""
    t = _tracker()
    recent = t.get_cost_by_day(days=7)
    if not recent:
        return {
            "daily_rate": 0.0,
            "projected_cost": 0.0,
            "projection_days": days,
        }
    total_recent = sum(d["cost"] for d in recent)
    actual_days = len(recent) or 1
    daily_rate = total_recent / actual_days
    return {
        "daily_rate": round(daily_rate, 4),
        "projected_cost": round(daily_rate * days, 2),
        "projection_days": days,
        "based_on_days": actual_days,
    }
