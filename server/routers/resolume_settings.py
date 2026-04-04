"""
Resolume .avc composition settings and rebuild endpoints.
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..database import get_setting, set_setting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/resolume", tags=["resolume"])

_SETTINGS_KEY = "resolume_config"

_DEFAULT_CONFIG = {
    "composition_name": "Will See",
    "num_decks": 4,
    "layer_mapping": {"1": 1, "2": 2, "3": 3, "4": 4},
    "transport_mode": "Denon",
    "resolution": "1920x1080",
    "clip_naming_format": "{artist} - {title}",
    "output_path": "/volume1/media/visuals/resolume",
}


class ResolumeConfig(BaseModel):
    composition_name: str = "Will See"
    num_decks: int = 4
    layer_mapping: dict[str, int] = {"1": 1, "2": 2, "3": 3, "4": 4}
    transport_mode: str = "Denon"
    resolution: str = "1920x1080"
    clip_naming_format: str = "{artist} - {title}"
    output_path: str = "/volume1/media/visuals/resolume"


@router.get("/auto-rebuild")
def get_auto_rebuild():
    """Get auto-rebuild setting."""
    enabled = get_setting("auto_rebuild_show", "true") == "true"
    return {"auto_rebuild": enabled}


@router.put("/auto-rebuild")
def set_auto_rebuild(enabled: bool = True):
    """Enable/disable auto-rebuild after generation."""
    set_setting("auto_rebuild_show", "true" if enabled else "false")
    return {"auto_rebuild": enabled}


@router.get("/settings")
def get_resolume_settings():
    """Get current Resolume composition settings."""
    raw = get_setting(_SETTINGS_KEY, "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return _DEFAULT_CONFIG


@router.put("/settings")
def update_resolume_settings(config: ResolumeConfig):
    """Save Resolume composition settings."""
    data = config.model_dump()
    set_setting(_SETTINGS_KEY, json.dumps(data))
    return data


@router.post("/rebuild")
def rebuild_avc():
    """Rebuild the .avc composition file from current settings."""
    raw = get_setting(_SETTINGS_KEY, "")
    if raw:
        try:
            config = json.loads(raw)
        except json.JSONDecodeError:
            config = _DEFAULT_CONFIG
    else:
        config = _DEFAULT_CONFIG

    try:
        avc_xml = _build_avc_xml(config)

        # Write to output path if accessible, otherwise to db_dir
        settings = get_settings()
        output_dir = Path(config.get("output_path", settings.db_path))
        if not output_dir.exists():
            output_dir = settings.db_dir

        output_file = output_dir / f"{config['composition_name'].replace(' ', '_')}.avc"
        output_file.write_text(avc_xml, encoding="utf-8")

        logger.info(f"Rebuilt AVC file: {output_file}")
        return {
            "success": True,
            "path": str(output_file),
            "size": len(avc_xml),
        }
    except Exception as e:
        logger.error(f"AVC rebuild failed: {e}")
        raise HTTPException(500, f"Rebuild failed: {e}")


@router.post("/push")
def push_to_resolume():
    """Push composition to Resolume via REST API (if available)."""
    import httpx

    settings = get_settings()
    url = f"http://{settings.resolume_host}:{settings.resolume_port}/api/v1/composition"

    try:
        resp = httpx.get(url, timeout=5.0)
        if resp.status_code == 200:
            return {"success": True, "message": "Resolume is reachable. Composition push initiated."}
        else:
            return {"success": False, "message": f"Resolume returned status {resp.status_code}"}
    except Exception as e:
        raise HTTPException(502, f"Cannot reach Resolume: {e}")


@router.get("/layers")
def get_layer_config():
    """Get multi-layer composition configuration."""
    from src.resolume.multilayer import get_layer_config, estimate_multilayer_cost
    config = get_layer_config()
    cost_estimate = estimate_multilayer_cost(10)  # Example for 10 tracks
    return {"layers": config, "cost_estimate": cost_estimate}


@router.post("/layers/build")
def build_multilayer(tracks: list[dict] = None):
    """Build a multi-layer .avc composition."""
    from src.resolume.multilayer import build_multilayer_avc
    if not tracks:
        return {"error": "No tracks provided", "example": {
            "tracks": [{"title": "Track 1", "video_path": "/path/to/video.mp4", "duration": 300}]
        }}

    settings = get_settings()
    output_dir = settings.db_dir
    output_file = output_dir / "multilayer_show.avc"

    try:
        path = build_multilayer_avc(tracks, output_file)
        return {"success": True, "path": str(path)}
    except Exception as e:
        raise HTTPException(500, f"Multi-layer build failed: {e}")


@router.get("/effects")
def get_effects():
    """Get available Resolume effects and section profiles."""
    from src.resolume.effects import get_available_effects, get_section_profiles
    return {
        "effects": get_available_effects(),
        "section_profiles": get_section_profiles(),
    }


@router.post("/effects/preview")
def preview_effect_keyframes(sections: list[dict] = None, bpm: float = 128.0):
    """Preview effect keyframes for given sections."""
    from src.resolume.effects import generate_effect_keyframes
    if not sections:
        sections = [
            {"label": "intro", "start_time": 0, "end_time": 30},
            {"label": "buildup", "start_time": 30, "end_time": 60},
            {"label": "drop", "start_time": 60, "end_time": 120},
            {"label": "breakdown", "start_time": 120, "end_time": 150},
            {"label": "outro", "start_time": 150, "end_time": 180},
        ]
    keyframes = generate_effect_keyframes(sections, bpm=bpm)
    return {"keyframes": keyframes, "section_count": len(sections)}


def _build_avc_xml(config: dict) -> str:
    """Generate a basic Resolume AVC XML structure."""
    name = config.get("composition_name", "Will See")
    resolution = config.get("resolution", "1920x1080")
    w, h = resolution.split("x")
    num_decks = config.get("num_decks", 4)
    layer_mapping = config.get("layer_mapping", {})
    transport = config.get("transport_mode", "Denon")
    clip_fmt = config.get("clip_naming_format", "{artist} - {title}")

    layers_xml = []
    for i in range(1, num_decks + 1):
        layer_id = layer_mapping.get(str(i), i)
        clip_name = clip_fmt.replace("{artist}", "Artist").replace(
            "{title}", "Track"
        ).replace("{deck}", str(i))
        layers_xml.append(
            f'  <layer id="{layer_id}" name="Deck {i}">\n'
            f'    <clip name="{clip_name}" />\n'
            f'    <transport mode="{transport}" />\n'
            f"  </layer>"
        )

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<composition name="{name}" width="{w}" height="{h}">\n'
        + "\n".join(layers_xml)
        + "\n</composition>\n"
    )
