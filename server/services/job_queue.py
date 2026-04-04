"""
Async job queue — processes video generation jobs sequentially.
Runs FullSongPipeline.generate_for_track() in a thread pool and
broadcasts progress via WebSocket.
"""
import asyncio
import json
import logging
import os
import tempfile
import time
import traceback
from pathlib import Path
from typing import Optional

from ..config import get_settings
from ..database import create_job, get_job, update_job
from ..websocket import ws_manager

logger = logging.getLogger(__name__)

# Module-level queue and worker task
_queue: asyncio.Queue | None = None
_worker_task: asyncio.Task | None = None


async def _get_or_create_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


async def enqueue_job(
    job_id: str,
    track: dict,
    brand: str = "will_see",
    quality: str = "high",
):
    """Add a job to the processing queue."""
    q = await _get_or_create_queue()
    await q.put({
        "job_id": job_id,
        "track": track,
        "brand": brand,
        "quality": quality,
    })
    logger.info(f"Job {job_id} enqueued (queue size: {q.qsize()})")


async def start_worker():
    """Start the background worker loop."""
    global _worker_task, _queue
    _queue = asyncio.Queue()
    if _worker_task is not None and not _worker_task.done():
        return
    _worker_task = asyncio.create_task(_worker_loop())
    logger.info("Job queue worker started")


async def stop_worker():
    """Stop the background worker."""
    global _worker_task, _queue
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    _queue = None
    logger.info("Job queue worker stopped")


async def _worker_loop():
    """Process jobs one at a time from the queue."""
    q = await _get_or_create_queue()
    while True:
        try:
            item = await q.get()
            await _process_job(item)
            q.task_done()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Unhandled error in job worker")


async def _process_job(item: dict):
    """Run a single generation job in a thread pool."""
    job_id = item["job_id"]
    track = item["track"]
    brand_name = item.get("brand", "will_see")
    quality = item.get("quality", "high")

    # Check if job was cancelled before we start
    job = get_job(job_id)
    if not job or job["status"] == "cancelled":
        logger.info(f"Job {job_id} already cancelled, skipping")
        return

    update_job(job_id, status="running", started_at=_now())
    await ws_manager.send_job_update(job_id, "running", 0.0, "Starting pipeline...")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, _run_pipeline_sync, job_id, track, brand_name, quality
        )
        update_job(
            job_id,
            status="completed",
            progress=1.0,
            progress_message="Done",
            result_json=json.dumps(result),
            cost=result.get("cost", 0.0),
            completed_at=_now(),
        )
        await ws_manager.send_job_update(
            job_id, "completed", 1.0, "Generation complete", result=result
        )

        # Auto-rebuild show if enabled
        try:
            from ..database import get_setting
            if get_setting("auto_rebuild_show", "true") == "true":
                from ..routers.resolume_settings import rebuild_avc
                rebuild_avc()
                logger.info(f"Auto-rebuilt show after job {job_id} completed")
        except Exception:
            logger.debug("Auto-rebuild failed (non-critical)", exc_info=True)

        # Send Discord notification
        try:
            from .notifications import notify_generation_complete
            started = job.get("started_at", "")
            elapsed = time.time() - time.mktime(time.strptime(started, "%Y-%m-%dT%H:%M:%SZ")) if started else 0
            await notify_generation_complete(
                track_title=track.get("title", "Unknown"),
                track_artist=track.get("artist", ""),
                cost=result.get("cost", 0.0),
                duration_secs=elapsed,
                model=result.get("model", ""),
            )
        except Exception:
            logger.debug("Discord notification failed (non-critical)", exc_info=True)

    except Exception as exc:
        error_str = str(exc).lower()
        error_msg = f"{type(exc).__name__}: {exc}"

        # Detect credit exhaustion specifically
        is_credit_error = any(
            kw in error_str
            for kw in ("exhausted", "balance", "insufficient", "credits")
        )
        if is_credit_error:
            error_msg = f"CREDITS_EXHAUSTED: {exc}"
            logger.error(
                f"Job {job_id} failed — fal.ai credits exhausted. "
                "Top up at https://fal.ai/dashboard/billing"
            )
            # Invalidate credit cache so dashboard picks it up immediately
            try:
                from ..routers.system import _credit_cache
                _credit_cache["result"] = None
                _credit_cache["checked_at"] = 0
            except Exception:
                pass
        else:
            logger.error(f"Job {job_id} failed: {error_msg}")

        update_job(
            job_id,
            status="failed",
            error=error_msg,
            completed_at=_now(),
        )
        await ws_manager.send_job_update(job_id, "failed", message=error_msg)

        # Send Discord notification for failure
        try:
            from .notifications import notify_generation_failed
            await notify_generation_failed(
                track_title=track.get("title", "Unknown"),
                track_artist=track.get("artist", ""),
                error=error_msg,
            )
        except Exception:
            logger.debug("Discord notification failed (non-critical)", exc_info=True)


def _run_pipeline_sync(
    job_id: str,
    track: dict,
    brand_name: str,
    quality: str,
) -> dict:
    """Synchronous pipeline execution (runs in thread pool)."""
    import yaml
    from src.pipeline import FullSongPipeline, _load_brand_config
    from src.nas import NASManager
    from src.cost_guard import CostGuard

    settings = get_settings()
    brand_config = _load_brand_config(brand_name)
    # Use the show-specific base path so videos land in the correct folder:
    show_base = os.environ.get("NAS_SHOW_BASE", "/volume1/vj-content/Show/Songs")
    resolume_mount = os.environ.get("RESOLUME_SHOW_MOUNT", "/Volumes/vj-content/Show/Songs")

    # Detect if running inside Docker container (vj-content mounted at /vj-content)
    direct = "/vj-content" if Path("/vj-content").is_dir() else ""

    nas = NASManager(
        nas_host=settings.nas_host,
        nas_port=settings.nas_ssh_port,
        nas_user=settings.nas_user,
        ssh_key=Path(settings.nas_ssh_key),
        base_path=show_base,
        resolume_mount=resolume_mount,
        direct_path=direct,
    )

    # Load cost protection settings from DB
    from ..database import get_setting
    max_cost = float(get_setting("cost_cap_per_song", "30.0"))
    auto_downgrade = get_setting("cost_auto_downgrade", "true") == "true"

    # Set up cost guard with segment cache
    cache_dir = Path(settings.db_path) / "segment_cache"
    cost_guard = CostGuard(
        max_cost=max_cost,
        auto_downgrade=auto_downgrade,
        cache_dir=cache_dir,
    )

    pipeline = FullSongPipeline(
        brand_config=brand_config,
        fal_key=settings.fal_key,
        openai_key=settings.openai_api_key,
        nas_manager=nas,
        cost_guard=cost_guard,
    )

    with tempfile.TemporaryDirectory(prefix="rsv_") as tmpdir:
        result = pipeline.generate_for_track(
            track=track,
            output_dir=Path(tmpdir),
            quality=quality,
        )

    return result


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
