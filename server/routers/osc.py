"""
OSC (Open Sound Control) management endpoints.
Issue #42: Live OSC parameter control for real-time visual adjustment.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_setting, set_setting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/osc", tags=["osc"])

_OSC_CONFIG_KEY = "osc_config"

_DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 7000,
    "enabled": False,
    "mappings": {
        "beat_pulse": "/composition/tempocontroller/tempo",
        "energy": "/composition/layers/1/video/opacity",
        "bass": "/composition/layers/1/video/effects/colorize/param1",
        "mid": "/composition/layers/1/video/effects/colorize/param2",
        "high": "/composition/layers/1/video/effects/colorize/param3",
        "section_change": "/composition/layers/1/clips/*/connect",
    },
    "stagelinq_enabled": False,
    "stagelinq_interface": "",
}

# Common Resolume OSC addresses for quick reference
RESOLUME_OSC_ADDRESSES = {
    "master_opacity": "/composition/master/video/opacity",
    "master_tempo": "/composition/tempocontroller/tempo",
    "layer_opacity": "/composition/layers/{layer}/video/opacity",
    "layer_bypass": "/composition/layers/{layer}/bypassed",
    "clip_connect": "/composition/layers/{layer}/clips/{clip}/connect",
    "clip_speed": "/composition/layers/{layer}/clips/{clip}/transport/position/behaviour/speed",
    "effect_opacity": "/composition/layers/{layer}/video/effects/{effect}/opacity",
    "effect_param": "/composition/layers/{layer}/video/effects/{effect}/params/{param}",
    "crossfader": "/composition/crossfader/phase",
    "column_trigger": "/composition/columns/{column}/connect",
}


class OscConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7000
    enabled: bool = False
    mappings: dict = {}
    stagelinq_enabled: bool = False
    stagelinq_interface: str = ""


class OscMessage(BaseModel):
    address: str
    value: float = 1.0


@router.get("/config")
def get_osc_config():
    """Get OSC configuration."""
    raw = get_setting(_OSC_CONFIG_KEY, "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return _DEFAULT_CONFIG


@router.put("/config")
def update_osc_config(config: OscConfig):
    """Update OSC configuration."""
    data = config.model_dump()
    set_setting(_OSC_CONFIG_KEY, json.dumps(data))
    return data


@router.get("/addresses")
def get_osc_addresses():
    """Get common Resolume OSC addresses for reference."""
    return {"addresses": RESOLUME_OSC_ADDRESSES}


@router.post("/send")
def send_osc_message(msg: OscMessage):
    """Send a single OSC message to Resolume."""
    raw = get_setting(_OSC_CONFIG_KEY, "")
    config = _DEFAULT_CONFIG
    if raw:
        try:
            config = json.loads(raw)
        except json.JSONDecodeError:
            pass

    host = config.get("host", "127.0.0.1")
    port = config.get("port", 7000)

    try:
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient(host, port)
        client.send_message(msg.address, msg.value)
        return {"sent": True, "address": msg.address, "value": msg.value, "target": f"{host}:{port}"}
    except ImportError:
        # python-osc not installed — return info about what would be sent
        return {
            "sent": False,
            "address": msg.address,
            "value": msg.value,
            "target": f"{host}:{port}",
            "error": "python-osc not installed. Install with: pip install python-osc",
        }
    except Exception as e:
        raise HTTPException(502, f"Failed to send OSC message: {e}")


@router.post("/test")
def test_osc_connection():
    """Test OSC connectivity by sending a tempo query."""
    raw = get_setting(_OSC_CONFIG_KEY, "")
    config = _DEFAULT_CONFIG
    if raw:
        try:
            config = json.loads(raw)
        except json.JSONDecodeError:
            pass

    host = config.get("host", "127.0.0.1")
    port = config.get("port", 7000)

    try:
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient(host, port)
        # Send a benign query
        client.send_message("/composition/tempocontroller/tempo", 0.0)
        return {"success": True, "message": f"OSC message sent to {host}:{port}"}
    except ImportError:
        return {
            "success": False,
            "message": "python-osc not installed. Install with: pip install python-osc",
        }
    except Exception as e:
        return {"success": False, "message": f"OSC error: {e}"}


@router.get("/presets")
def list_osc_presets():
    """List predefined OSC mapping presets for common use cases."""
    presets = [
        {
            "name": "Beat Reactive",
            "description": "Maps beat detection to layer opacity and effect intensity",
            "mappings": {
                "beat_pulse": "/composition/layers/1/video/opacity",
                "energy": "/composition/layers/1/video/effects/1/opacity",
                "bass": "/composition/layers/1/video/effects/2/params/1",
            },
        },
        {
            "name": "Color Wash",
            "description": "Maps frequency bands to RGB colorize effect",
            "mappings": {
                "bass": "/composition/layers/1/video/effects/colorize/param1",
                "mid": "/composition/layers/1/video/effects/colorize/param2",
                "high": "/composition/layers/1/video/effects/colorize/param3",
            },
        },
        {
            "name": "Section Transitions",
            "description": "Triggers clip changes on section boundaries",
            "mappings": {
                "section_change": "/composition/columns/{column}/connect",
                "energy": "/composition/master/video/opacity",
            },
        },
        {
            "name": "Strobe & Flash",
            "description": "Beat-synced strobe with energy-driven intensity",
            "mappings": {
                "beat_pulse": "/composition/layers/2/video/effects/strobe/rate",
                "energy": "/composition/layers/2/video/effects/strobe/opacity",
            },
        },
    ]
    return {"presets": presets}
