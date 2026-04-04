"""
Setup status and wizard endpoints.
Checks which services are configured and returns setup completion state.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from ..config import get_settings
from ..database import get_setting, set_setting

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status")
def setup_status():
    """Return which services are configured and which aren't.

    Used by the frontend to decide whether to show the setup wizard.
    Setup is considered complete if:
    - The user has explicitly dismissed the wizard, OR
    - The core infrastructure sections (NAS + Lexicon) are configured.
    API keys are NOT required for setup — they're only needed for generation
    and may be injected at runtime via `op run` or similar.
    """
    settings = get_settings()

    # Check if setup was explicitly dismissed
    dismissed = get_setting("setup_dismissed", "") == "true"

    checks = {
        "api_keys": {
            "fal_key": {
                "configured": bool(settings.fal_key),
                "required": False,
                "label": "fal.ai API Key",
            },
            "openai_api_key": {
                "configured": bool(settings.openai_api_key),
                "required": False,
                "label": "OpenAI API Key",
            },
        },
        "nas": {
            "host": {
                "configured": bool(settings.nas_host),
                "value": settings.nas_host if settings.nas_host else None,
                "required": True,
                "label": "NAS Host",
            },
            "ssh_port": {
                "configured": bool(settings.nas_ssh_port),
                "value": settings.nas_ssh_port,
                "required": True,
                "label": "NAS SSH Port",
            },
            "user": {
                "configured": bool(settings.nas_user),
                "value": settings.nas_user if settings.nas_user else None,
                "required": True,
                "label": "NAS User",
            },
            "ssh_key": {
                "configured": bool(settings.nas_ssh_key),
                "required": True,
                "label": "SSH Key Path",
            },
        },
        "lexicon": {
            "host": {
                "configured": bool(settings.lexicon_host),
                "value": settings.lexicon_host,
                "required": True,
                "label": "Lexicon Host",
            },
            "port": {
                "configured": bool(settings.lexicon_port),
                "value": settings.lexicon_port,
                "required": True,
                "label": "Lexicon Port",
            },
        },
        "resolume": {
            "host": {
                "configured": bool(settings.resolume_host),
                "value": settings.resolume_host,
                "required": False,
                "label": "Resolume Host",
            },
            "port": {
                "configured": bool(settings.resolume_port),
                "value": settings.resolume_port,
                "required": False,
                "label": "Resolume Port",
            },
        },
    }

    # A section is complete if all required fields are configured
    sections = {}
    for section_name, fields in checks.items():
        required_fields = {k: v for k, v in fields.items() if v["required"]}
        all_configured = all(f["configured"] for f in required_fields.values()) if required_fields else bool(any(f["configured"] for f in fields.values()))
        sections[section_name] = {
            "complete": all_configured,
            "fields": fields,
        }

    # Core infrastructure: NAS and Lexicon must be configured
    required_sections = ["nas", "lexicon"]
    infra_complete = all(sections[s]["complete"] for s in required_sections)

    # Setup is complete if dismissed OR infrastructure is configured
    setup_complete = dismissed or infra_complete

    return {
        "setup_complete": setup_complete,
        "setup_dismissed": dismissed,
        "sections": sections,
    }


@router.post("/dismiss")
def dismiss_setup():
    """Mark setup as dismissed. The wizard won't show again."""
    set_setting("setup_dismissed", "true")
    return {"ok": True}


@router.post("/reset")
def reset_setup():
    """Reset the setup dismissed flag. The wizard will show again if infra isn't configured."""
    set_setting("setup_dismissed", "")
    return {"ok": True}
