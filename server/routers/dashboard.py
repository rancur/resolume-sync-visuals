"""
Dashboard and system status endpoints.
"""
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..config import get_settings
from ..database import get_db, get_setting, set_setting, list_jobs

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard")
def get_dashboard():
    """Aggregated dashboard stats."""
    settings = get_settings()
    paused = get_setting("generation_paused", "false") == "true"

    # Job stats
    jobs = list_jobs(limit=200)
    active = [j for j in jobs if j["status"] in ("running", "active")]
    queued = [j for j in jobs if j["status"] == "queued"]
    completed = [j for j in jobs if j["status"] == "completed"]
    total_cost = sum(j.get("cost", 0) or 0 for j in jobs)

    # Track counts from completed jobs (unique track_ids)
    track_ids_with_visuals = set()
    all_track_ids = set()
    for j in jobs:
        tid = j.get("track_id", "")
        if tid:
            all_track_ids.add(tid)
            if j["status"] == "completed":
                track_ids_with_visuals.add(tid)

    # Try to get total tracks from Lexicon
    total_tracks = len(all_track_ids)
    try:
        from ..services.lexicon_service import get_lexicon_service
        svc = get_lexicon_service()
        tracks = svc.get_tracks(limit=1)
        if tracks and "total" in tracks:
            total_tracks = max(total_tracks, tracks["total"])
    except Exception:
        pass

    # Recent activity (last 10 completed/failed)
    recent = [j for j in jobs if j["status"] in ("completed", "failed")][:10]
    recent_activity = [
        {
            "id": j["id"],
            "track_id": j.get("track_id", ""),
            "track_title": j.get("track_title", ""),
            "track_artist": j.get("track_artist", ""),
            "status": j["status"],
            "cost": j.get("cost", 0) or 0,
            "completed_at": j.get("completed_at", ""),
        }
        for j in recent
    ]

    # System health
    health = _get_system_health()

    return {
        "total_tracks": total_tracks,
        "tracks_with_visuals": len(track_ids_with_visuals),
        "total_cost": total_cost,
        "active_jobs": len(active),
        "queued_jobs": len(queued),
        "paused": paused,
        "recent_activity": recent_activity,
        "health": health,
    }


@router.get("/api/system/status")
def get_system_status():
    """Check connectivity to all external services."""
    settings = get_settings()
    result = {}

    # NAS check — we run ON the NAS in Docker, so SSH to self won't work.
    # Instead, verify we can access the filesystem (mounted volume).
    try:
        db_dir = Path(settings.db_path)
        if db_dir.exists():
            usage = shutil.disk_usage(str(db_dir))
            disk_free = _fmt_bytes(usage.free)
            result["nas"] = {
                "connected": True,
                "status": "online",
                "detail": f"{disk_free} free",
            }
        else:
            result["nas"] = {
                "connected": True,
                "status": "online",
                "detail": "Running on NAS",
            }
    except Exception as e:
        result["nas"] = {
            "connected": True,
            "status": "online",
            "detail": "Running on NAS",
        }

    # Lexicon check — short timeout since it's on the LAN
    try:
        from ..services.lexicon_service import get_lexicon_service
        svc = get_lexicon_service()
        test = svc.test_connection()
        connected = test.get("connected", test.get("ok", False))
        result["lexicon"] = {
            "connected": connected,
            "status": "online" if connected else "offline",
            "track_count": test.get("track_count"),
        }
    except Exception as e:
        result["lexicon"] = {
            "connected": False,
            "status": "unknown",
            "error": "Cannot reach Lexicon — is it running?",
        }

    # fal.ai check — use cached credit status if available
    if not settings.fal_key:
        result["fal"] = {
            "connected": False,
            "status": "not_configured",
            "error": "No API key configured",
        }
    else:
        # Check if we have a cached credit result
        try:
            from .system import _credit_cache
            cached = _credit_cache.get("result")
            if cached and cached.get("status") == "exhausted":
                result["fal"] = {
                    "connected": False,
                    "status": "offline",
                    "detail": "Credits exhausted",
                    "error": "fal.ai credits exhausted — top up at fal.ai/dashboard/billing",
                }
            elif cached and cached.get("status") == "active":
                result["fal"] = {
                    "connected": True,
                    "status": "online",
                    "detail": "Credits available",
                }
            else:
                # Also check if recent jobs failed with credit errors
                recent_jobs = list_jobs(status="failed", limit=5)
                credit_fails = [
                    j for j in recent_jobs
                    if "CREDITS_EXHAUSTED" in (j.get("error") or "")
                ]
                if credit_fails:
                    result["fal"] = {
                        "connected": False,
                        "status": "offline",
                        "detail": "Credits exhausted (detected from failed jobs)",
                        "error": "fal.ai credits exhausted — top up at fal.ai/dashboard/billing",
                    }
                else:
                    result["fal"] = {
                        "connected": True,
                        "status": "online",
                        "detail": "API key configured",
                    }
        except Exception:
            result["fal"] = {
                "connected": True,
                "status": "online",
                "detail": "API key configured",
            }

    # Resolume check — short timeout, graceful when not running
    if not settings.resolume_host or settings.resolume_host == "127.0.0.1":
        result["resolume"] = {
            "connected": False,
            "status": "not_configured",
            "detail": "Not configured — set RESOLUME_HOST",
        }
    else:
        try:
            import httpx
            url = f"http://{settings.resolume_host}:{settings.resolume_port}/api/v1/composition"
            resp = httpx.get(url, timeout=2.0)
            result["resolume"] = {
                "connected": True,
                "status": "online",
            }
        except Exception:
            result["resolume"] = {
                "connected": False,
                "status": "not_running",
                "detail": "Resolume not reachable — is it running?",
            }

    return result


@router.post("/api/system/pause")
def pause_generation():
    """Pause the generation queue."""
    set_setting("generation_paused", "true")
    return {"paused": True}


@router.post("/api/system/resume")
def resume_generation():
    """Resume the generation queue."""
    set_setting("generation_paused", "false")
    return {"paused": False}


@router.get("/api/system/storage")
def get_storage_status():
    """Detailed disk usage with alert thresholds."""
    settings = get_settings()
    result = {
        "local": _get_disk_info("/"),
        "output": _get_disk_info(settings.db_path),
        "thresholds": {"warn_percent": 80, "critical_percent": 90},
        "alerts": [],
    }

    # Check thresholds
    for name, info in [("local", result["local"]), ("output", result["output"])]:
        if info and info.get("percent"):
            if info["percent"] >= 90:
                result["alerts"].append({
                    "level": "critical",
                    "message": f"{name} disk at {info['percent']}% — cleanup urgently needed",
                })
            elif info["percent"] >= 80:
                result["alerts"].append({
                    "level": "warning",
                    "message": f"{name} disk at {info['percent']}% — approaching limit",
                })

    # Count generated files
    db_path = Path(settings.db_path)
    output_dirs = [db_path / "output", db_path / "keyframes", db_path / "previews"]
    file_stats = {}
    for d in output_dirs:
        if d.exists():
            files = list(d.rglob("*"))
            file_count = sum(1 for f in files if f.is_file())
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            file_stats[d.name] = {
                "count": file_count,
                "size": _fmt_bytes(total_size),
                "size_bytes": total_size,
            }
    result["file_stats"] = file_stats

    return result


def _get_disk_info(path: str) -> dict:
    try:
        usage = shutil.disk_usage(path)
        return {
            "used": _fmt_bytes(usage.used),
            "free": _fmt_bytes(usage.free),
            "total": _fmt_bytes(usage.total),
            "percent": round(usage.used / usage.total * 100, 1),
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "total_bytes": usage.total,
        }
    except Exception:
        return {}


@router.post("/api/system/cleanup")
def run_cleanup(dry_run: bool = Query(True)):
    """Smart cleanup of generated files. Use dry_run=true to preview."""
    settings = get_settings()
    db_path = Path(settings.db_path)
    cleanup_plan = []
    total_freed = 0

    # Priority 1: Preview/draft renders
    preview_dir = db_path / "previews"
    if preview_dir.exists():
        for f in sorted(preview_dir.rglob("*"), key=lambda p: p.stat().st_mtime if p.is_file() else 0):
            if f.is_file():
                size = f.stat().st_size
                cleanup_plan.append({
                    "path": str(f.relative_to(db_path)),
                    "size": _fmt_bytes(size),
                    "size_bytes": size,
                    "priority": 1,
                    "reason": "Preview/draft (regeneratable)",
                })
                total_freed += size
                if not dry_run:
                    f.unlink()

    # Priority 2: Failed generation artifacts
    output_dir = db_path / "output"
    if output_dir.exists():
        for f in output_dir.rglob("*.failed"):
            if f.is_file():
                size = f.stat().st_size
                cleanup_plan.append({
                    "path": str(f.relative_to(db_path)),
                    "size": _fmt_bytes(size),
                    "size_bytes": size,
                    "priority": 2,
                    "reason": "Failed generation artifact",
                })
                total_freed += size
                if not dry_run:
                    f.unlink()

    # Priority 3: Temp files
    for temp_pattern in ["*.tmp", "*.partial"]:
        for d in [db_path / "output", db_path / "keyframes"]:
            if d.exists():
                for f in d.rglob(temp_pattern):
                    if f.is_file():
                        size = f.stat().st_size
                        cleanup_plan.append({
                            "path": str(f.relative_to(db_path)),
                            "size": _fmt_bytes(size),
                            "size_bytes": size,
                            "priority": 3,
                            "reason": "Temporary file",
                        })
                        total_freed += size
                        if not dry_run:
                            f.unlink()

    return {
        "dry_run": dry_run,
        "items": cleanup_plan,
        "total_items": len(cleanup_plan),
        "total_freed": _fmt_bytes(total_freed),
        "total_freed_bytes": total_freed,
    }


def _get_system_health() -> dict:
    """Get basic system health metrics."""
    health = {}

    # Disk usage
    try:
        usage = shutil.disk_usage("/")
        health["disk_used"] = _fmt_bytes(usage.used)
        health["disk_total"] = _fmt_bytes(usage.total)
        health["disk_percent"] = round(usage.used / usage.total * 100, 1)
    except Exception:
        pass

    # Memory (try psutil, fall back gracefully)
    try:
        import psutil
        mem = psutil.virtual_memory()
        health["memory_used"] = _fmt_bytes(mem.used)
        health["memory_total"] = _fmt_bytes(mem.total)
        health["memory_percent"] = round(mem.percent, 1)
    except ImportError:
        pass
    except Exception:
        pass

    # Container uptime (check /proc/1/stat if available)
    try:
        with open("/proc/uptime") as f:
            uptime_secs = float(f.read().split()[0])
            days = int(uptime_secs // 86400)
            hours = int((uptime_secs % 86400) // 3600)
            health["uptime"] = f"{days}d {hours}h" if days > 0 else f"{hours}h {int((uptime_secs % 3600) // 60)}m"
    except Exception:
        pass

    return health


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
