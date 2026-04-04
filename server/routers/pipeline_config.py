"""
Pipeline configuration endpoints.
Issue #50: Progressive rendering (preview + final pass).
Issue #51: Parallel generation across multiple API keys.
"""
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..database import get_setting, set_setting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# ── Issue #50: Progressive Rendering ──

_PROGRESSIVE_KEY = "progressive_rendering_config"

_DEFAULT_PROGRESSIVE = {
    "enabled": False,
    "auto_approve": False,
    "preview": {
        "resolution": "480p",
        "quality": "draft",
        "model_override": "",  # Empty = use fastest available
        "segment_duration": 5,
    },
    "final": {
        "resolution": "1080p",
        "quality": "high",
        "model_override": "",
        "segment_duration": 10,
    },
    "cost_savings_estimate": "~70% on rejected generations",
}


class ProgressiveConfig(BaseModel):
    enabled: bool = False
    auto_approve: bool = False
    preview: dict = {}
    final: dict = {}


@router.get("/progressive")
def get_progressive_config():
    """Get progressive rendering configuration."""
    raw = get_setting(_PROGRESSIVE_KEY, "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return _DEFAULT_PROGRESSIVE


@router.put("/progressive")
def update_progressive_config(config: ProgressiveConfig):
    """Update progressive rendering settings."""
    data = config.model_dump()
    set_setting(_PROGRESSIVE_KEY, json.dumps(data))
    return data


@router.get("/progressive/stats")
def get_progressive_stats():
    """Get cost savings stats from progressive rendering."""
    # Return mock stats until real tracking is implemented
    return {
        "total_previews": 0,
        "approved": 0,
        "rejected": 0,
        "regenerated": 0,
        "preview_cost": 0.0,
        "final_cost": 0.0,
        "savings": 0.0,
        "approval_rate": 0.0,
    }


# ── Issue #51: Parallel API Keys ──

_API_KEYS_KEY = "api_key_pool"

_DEFAULT_KEY_POOL = {
    "fal": [],
    "kling": [],
    "runway": [],
    "replicate": [],
    "distribution_strategy": "least_loaded",  # round_robin, least_loaded
    "auto_remove_unhealthy": True,
}


class ApiKeyEntry(BaseModel):
    key: str
    label: str = ""
    rate_limit: int = 10  # requests per minute
    budget_limit: Optional[float] = None  # optional per-key budget


class ApiKeyPoolConfig(BaseModel):
    provider: str
    keys: list[ApiKeyEntry]
    distribution_strategy: str = "least_loaded"


@router.get("/api-keys")
def get_api_key_pool():
    """Get API key pool configuration (keys are masked)."""
    raw = get_setting(_API_KEYS_KEY, "")
    pool = _DEFAULT_KEY_POOL.copy()
    if raw:
        try:
            pool = json.loads(raw)
        except json.JSONDecodeError:
            pass

    # Mask keys for security
    masked = {}
    for provider, keys in pool.items():
        if isinstance(keys, list):
            masked[provider] = [
                {
                    **k,
                    "key": k["key"][:8] + "..." + k["key"][-4:] if len(k.get("key", "")) > 12 else "***",
                    "status": "healthy",
                }
                for k in keys
                if isinstance(k, dict)
            ]
        else:
            masked[provider] = keys

    return masked


@router.put("/api-keys/{provider}")
def update_api_keys(provider: str, config: ApiKeyPoolConfig):
    """Update API keys for a provider."""
    raw = get_setting(_API_KEYS_KEY, "")
    pool = _DEFAULT_KEY_POOL.copy()
    if raw:
        try:
            pool = json.loads(raw)
        except json.JSONDecodeError:
            pass

    pool[provider] = [k.model_dump() for k in config.keys]
    pool["distribution_strategy"] = config.distribution_strategy
    set_setting(_API_KEYS_KEY, json.dumps(pool))

    return {"provider": provider, "key_count": len(config.keys)}


@router.post("/api-keys/{provider}/add")
def add_api_key(provider: str, entry: ApiKeyEntry):
    """Add a single API key to the pool."""
    raw = get_setting(_API_KEYS_KEY, "")
    pool = _DEFAULT_KEY_POOL.copy()
    if raw:
        try:
            pool = json.loads(raw)
        except json.JSONDecodeError:
            pass

    if provider not in pool:
        pool[provider] = []
    if not isinstance(pool[provider], list):
        pool[provider] = []

    pool[provider].append(entry.model_dump())
    set_setting(_API_KEYS_KEY, json.dumps(pool))

    return {"provider": provider, "key_count": len(pool[provider])}


@router.delete("/api-keys/{provider}/{index}")
def remove_api_key(provider: str, index: int):
    """Remove an API key by index."""
    raw = get_setting(_API_KEYS_KEY, "")
    pool = _DEFAULT_KEY_POOL.copy()
    if raw:
        try:
            pool = json.loads(raw)
        except json.JSONDecodeError:
            pass

    keys = pool.get(provider, [])
    if not isinstance(keys, list) or index >= len(keys):
        raise HTTPException(404, "Key not found")

    keys.pop(index)
    pool[provider] = keys
    set_setting(_API_KEYS_KEY, json.dumps(pool))

    return {"removed": True, "provider": provider, "remaining": len(keys)}


@router.get("/api-keys/status")
def get_key_pool_status():
    """Get health and usage status of all API keys."""
    raw = get_setting(_API_KEYS_KEY, "")
    pool = _DEFAULT_KEY_POOL.copy()
    if raw:
        try:
            pool = json.loads(raw)
        except json.JSONDecodeError:
            pass

    status = {}
    for provider, keys in pool.items():
        if isinstance(keys, list):
            status[provider] = {
                "total_keys": len(keys),
                "healthy": len(keys),  # All healthy until we track failures
                "total_rate_limit": sum(k.get("rate_limit", 10) for k in keys if isinstance(k, dict)),
                "strategy": pool.get("distribution_strategy", "least_loaded"),
            }

    return {"providers": status}


# ── Batch Queue Priority (Issue #45 enhancement) ──

_SCHEDULE_KEY = "generation_schedule"

_DEFAULT_SCHEDULE = {
    "enabled": False,
    "start_time": "00:00",
    "end_time": "06:00",
    "timezone": "America/Phoenix",
    "concurrent_workers": 2,
    "priority_levels": ["urgent", "high", "normal", "low"],
}


@router.get("/schedule")
def get_schedule():
    """Get generation schedule configuration."""
    raw = get_setting(_SCHEDULE_KEY, "")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return _DEFAULT_SCHEDULE


@router.put("/schedule")
def update_schedule(config: dict):
    """Update generation schedule."""
    set_setting(_SCHEDULE_KEY, json.dumps(config))
    return config
