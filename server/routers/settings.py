"""
Settings management — read/write persistent config, test services.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..database import get_all_settings, get_setting, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Keys that should be masked in API responses
_SENSITIVE_KEYS = {"fal_key", "openai_api_key"}


@router.get("")
def get_all():
    settings = get_settings()
    env_settings = {
        "lexicon_host": settings.lexicon_host,
        "lexicon_port": settings.lexicon_port,
        "nas_host": settings.nas_host,
        "nas_ssh_port": settings.nas_ssh_port,
        "nas_user": settings.nas_user,
        "resolume_host": settings.resolume_host,
        "resolume_port": settings.resolume_port,
        "db_path": settings.db_path,
        "log_retention_days": settings.log_retention_days,
        # Masked secrets
        "fal_key": _mask(settings.fal_key),
        "openai_api_key": _mask(settings.openai_api_key),
    }
    db_settings = get_all_settings()
    # Mask sensitive values in db settings too
    for key in list(db_settings.keys()):
        if any(s in key.lower() for s in ("key", "secret", "token", "password")):
            db_settings[key] = _mask(str(db_settings[key]))
    return {"env": env_settings, "db": db_settings}


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, str]


@router.put("")
def update_settings(req: SettingsUpdateRequest):
    for key, value in req.settings.items():
        set_setting(key, value)
    return {"updated": list(req.settings.keys())}


@router.get("/cost-protection")
def get_cost_settings():
    """Get cost protection settings."""
    return {
        "cost_cap_per_song": float(get_setting("cost_cap_per_song", "30.0")),
        "cost_auto_downgrade": get_setting("cost_auto_downgrade", "true") == "true",
        "cost_confirm_threshold": float(get_setting("cost_confirm_threshold", "20.0")),
    }


class CostProtectionUpdate(BaseModel):
    cost_cap_per_song: float = 30.0
    cost_auto_downgrade: bool = True
    cost_confirm_threshold: float = 20.0


@router.put("/cost-protection")
def update_cost_settings(req: CostProtectionUpdate):
    """Update cost protection settings."""
    set_setting("cost_cap_per_song", str(req.cost_cap_per_song))
    set_setting("cost_auto_downgrade", "true" if req.cost_auto_downgrade else "false")
    set_setting("cost_confirm_threshold", str(req.cost_confirm_threshold))
    return {
        "cost_cap_per_song": req.cost_cap_per_song,
        "cost_auto_downgrade": req.cost_auto_downgrade,
        "cost_confirm_threshold": req.cost_confirm_threshold,
    }


@router.post("/test-lexicon")
def test_lexicon():
    from ..services.lexicon_service import get_lexicon_service

    svc = get_lexicon_service()
    result = svc.test_connection()
    return result


@router.post("/test-nas")
def test_nas():
    from src.nas import NASManager
    from ..config import get_settings
    from pathlib import Path

    settings = get_settings()
    nas = NASManager(
        nas_host=settings.nas_host,
        nas_port=settings.nas_ssh_port,
        nas_user=settings.nas_user,
        ssh_key=Path(settings.nas_ssh_key),
    )
    try:
        tracks = nas.list_tracks()
        return {"connected": True, "track_count": len(tracks)}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.post("/test-resolume")
def test_resolume():
    import httpx
    settings = get_settings()
    url = f"http://{settings.resolume_host}:{settings.resolume_port}/api/v1/composition"
    try:
        resp = httpx.get(url, timeout=5.0)
        return {"connected": True, "status_code": resp.status_code}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.post("/test-discord")
async def test_discord():
    """Test Discord webhook notification."""
    from ..services.notifications import send_test_notification, _is_enabled

    if not _is_enabled():
        return {"ok": False, "error": "No Discord webhook URL configured"}

    success = await send_test_notification()
    return {"ok": success, "error": "" if success else "Webhook delivery failed"}


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "***" if value else ""
    return value[:4] + "..." + value[-4:]
