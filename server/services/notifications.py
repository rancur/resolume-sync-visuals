"""
Notification service — send alerts via Discord webhooks.

Supports:
- Generation complete/failed per track
- Batch summary
- Disk space alerts
"""
import logging
from datetime import datetime
from typing import Optional

import httpx

from ..database import get_setting, set_setting

logger = logging.getLogger(__name__)


def _get_webhook_url() -> str:
    return get_setting("discord_webhook_url", "")


def _is_enabled() -> bool:
    return bool(_get_webhook_url())


async def notify_generation_complete(
    track_title: str,
    track_artist: str,
    cost: float,
    duration_secs: float,
    model: str = "",
    thumbnail_url: str = "",
):
    """Send Discord notification when a track's visuals are generated."""
    if not _is_enabled():
        return

    embed = {
        "title": "Visual Generated",
        "description": f"**{track_artist} - {track_title}**",
        "color": 0x4FC3F7,  # Brand blue
        "fields": [
            {"name": "Cost", "value": f"${cost:.4f}", "inline": True},
            {"name": "Time", "value": f"{duration_secs:.0f}s", "inline": True},
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }
    if model:
        embed["fields"].append({"name": "Model", "value": model, "inline": True})
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}

    await _send_webhook(embeds=[embed])


async def notify_generation_failed(
    track_title: str,
    track_artist: str,
    error: str,
):
    """Send Discord notification when generation fails."""
    if not _is_enabled():
        return

    embed = {
        "title": "Generation Failed",
        "description": f"**{track_artist} - {track_title}**",
        "color": 0xE57373,  # Red
        "fields": [
            {"name": "Error", "value": error[:1024], "inline": False},
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }
    await _send_webhook(embeds=[embed])


async def notify_batch_complete(
    succeeded: int,
    failed: int,
    total_cost: float,
    total_time_secs: float,
):
    """Send Discord summary when a batch generation finishes."""
    if not _is_enabled():
        return

    status = "All succeeded" if failed == 0 else f"{succeeded} succeeded, {failed} failed"
    color = 0x81C784 if failed == 0 else 0xFFB74D

    embed = {
        "title": "Batch Generation Complete",
        "description": status,
        "color": color,
        "fields": [
            {"name": "Tracks", "value": str(succeeded + failed), "inline": True},
            {"name": "Total Cost", "value": f"${total_cost:.2f}", "inline": True},
            {"name": "Duration", "value": f"{total_time_secs / 60:.1f}min", "inline": True},
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }
    await _send_webhook(embeds=[embed])


async def notify_disk_alert(level: str, message: str):
    """Send Discord alert for disk space issues."""
    if not _is_enabled():
        return

    color = 0xE57373 if level == "critical" else 0xFFB74D
    embed = {
        "title": f"Disk Alert: {level.upper()}",
        "description": message,
        "color": color,
        "timestamp": datetime.utcnow().isoformat(),
    }
    await _send_webhook(embeds=[embed])


async def send_test_notification():
    """Send a test notification to verify webhook configuration."""
    embed = {
        "title": "RSV Test Notification",
        "description": "Discord webhook is configured correctly.",
        "color": 0x4FC3F7,
        "timestamp": datetime.utcnow().isoformat(),
    }
    return await _send_webhook(embeds=[embed])


async def _send_webhook(
    content: str = "",
    embeds: Optional[list] = None,
) -> bool:
    """Send a message to the configured Discord webhook."""
    url = _get_webhook_url()
    if not url:
        return False

    payload = {"username": "RSV Bot"}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code in (200, 204):
                return True
            logger.warning(f"Discord webhook returned {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Discord webhook failed: {e}")
        return False
