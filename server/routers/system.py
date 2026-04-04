"""
System endpoints — version info, auto-update, Docker health, and credit checks.
"""
import logging
import os
import subprocess
import time

from fastapi import APIRouter

from ..config import get_settings
from ..services.updater import get_updater

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])

# Cache credit check results for 5 minutes — credit status changes rarely
_credit_cache: dict = {"result": None, "checked_at": 0}


@router.get("/version")
def get_version():
    """Return current version and latest available version."""
    updater = get_updater()
    return updater.check_for_updates()


@router.post("/update")
def trigger_update():
    """Pull latest image and restart container."""
    updater = get_updater()
    return updater.update()


@router.get("/docker")
def docker_status():
    """Return Docker container health info if running in Docker."""
    is_docker = (
        os.path.exists("/.dockerenv")
        or os.environ.get("DOCKER_CONTAINER") == "1"
    )

    result = {
        "running_in_docker": is_docker,
        "container_id": os.environ.get("HOSTNAME", ""),
        "image": os.environ.get("DOCKER_IMAGE", "unknown"),
        "uptime": None,
    }

    if is_docker:
        try:
            hostname = os.environ.get("HOSTNAME", "")
            if hostname:
                proc = subprocess.run(
                    ["docker", "inspect", "--format",
                     "{{.State.StartedAt}}", hostname],
                    capture_output=True, text=True, timeout=5,
                )
                if proc.returncode == 0:
                    result["uptime"] = proc.stdout.strip()
        except Exception as e:
            logger.debug("Could not get container uptime: %s", e)

    return result


@router.get("/credits")
def check_credits():
    """
    Check fal.ai credit status by making the cheapest possible API call.
    Returns status: 'active', 'exhausted', 'no_key', or 'error'.
    Results are cached for 60s to avoid excessive API calls.
    """
    global _credit_cache
    now = time.time()

    # Return cached result if fresh (5 min TTL)
    if _credit_cache["result"] and (now - _credit_cache["checked_at"]) < 300:
        return _credit_cache["result"]

    settings = get_settings()
    if not settings.fal_key:
        result = {
            "status": "no_key",
            "message": "No fal.ai API key configured",
            "checked_at": _iso_now(),
        }
        _credit_cache = {"result": result, "checked_at": now}
        return result

    try:
        import httpx

        # Validate API key by calling fal.ai's queue status endpoint (FREE).
        # Previous approach used Flux Schnell generation ($0.003/call = $4.32/day
        # at 60s polling). This costs nothing — it just checks auth.
        headers = {
            "Authorization": f"Key {settings.fal_key}",
            "Content-Type": "application/json",
        }
        # Hit a lightweight queue list endpoint — this validates the key
        # without running any model inference.
        resp = httpx.get(
            "https://queue.fal.run/fal-ai/flux/schnell/requests",
            headers=headers,
            timeout=10.0,
        )

        if resp.status_code == 200:
            result = {
                "status": "active",
                "message": "API key valid, credits assumed available",
                "test_cost": 0.0,
                "checked_at": _iso_now(),
            }
        elif resp.status_code == 401:
            result = {
                "status": "invalid_key",
                "message": "fal.ai API key is invalid",
                "error": f"HTTP {resp.status_code}",
                "checked_at": _iso_now(),
            }
        elif resp.status_code == 403:
            error_body = resp.text.lower()
            if "exhausted" in error_body or "balance" in error_body or "insufficient" in error_body:
                result = {
                    "status": "exhausted",
                    "message": "fal.ai credits exhausted. Top up at fal.ai/dashboard/billing",
                    "error": resp.text,
                    "checked_at": _iso_now(),
                }
            else:
                result = {
                    "status": "active",
                    "message": "API key valid (queue access restricted, credits assumed available)",
                    "test_cost": 0.0,
                    "checked_at": _iso_now(),
                }
        else:
            result = {
                "status": "active",
                "message": f"API key accepted (HTTP {resp.status_code})",
                "test_cost": 0.0,
                "checked_at": _iso_now(),
            }

        _credit_cache = {"result": result, "checked_at": now}
        return result

    except Exception as exc:
        error_str = str(exc).lower()
        if "exhausted" in error_str or "balance" in error_str or "insufficient" in error_str:
            result = {
                "status": "exhausted",
                "message": "fal.ai credits exhausted. Top up at fal.ai/dashboard/billing",
                "error": str(exc),
                "checked_at": _iso_now(),
            }
        elif "unauthorized" in error_str or "401" in error_str or "invalid" in error_str:
            result = {
                "status": "invalid_key",
                "message": "fal.ai API key is invalid",
                "error": str(exc),
                "checked_at": _iso_now(),
            }
        else:
            result = {
                "status": "error",
                "message": f"Could not verify credits: {exc}",
                "error": str(exc),
                "checked_at": _iso_now(),
            }

        _credit_cache = {"result": result, "checked_at": now}
        return result


@router.post("/credits/clear-cache")
def clear_credit_cache():
    """Force a fresh credit check on the next call."""
    global _credit_cache
    _credit_cache = {"result": None, "checked_at": 0}
    return {"cleared": True}


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@router.get("/release-notes")
def get_release_notes():
    """Return changelog / release notes for the latest available version."""
    updater = get_updater()
    info = updater.check_for_updates()
    return {
        "version": info["latest"],
        "changelog": info["changelog"],
        "published_at": info["published_at"],
        "html_url": info["html_url"],
    }
