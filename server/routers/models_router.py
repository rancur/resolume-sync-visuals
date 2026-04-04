"""
Video model configuration endpoints.

Serves the full model catalog to the frontend with quality ratings,
speed estimates, tier grouping, and cost info.
"""
from fastapi import APIRouter

from ..database import get_setting, set_setting

router = APIRouter(prefix="/api/models", tags=["models"])

# ── Video generation models ───────────────────────────────────────────────
# All models available via fal.ai (primary) or replicate.
# Quality: 1-5. Speed: "fast" / "medium" / "slow".
VIDEO_MODELS = [
    # Tier 1 — Best quality
    {
        "id": "kling-v1",
        "name": "Kling v1",
        "provider": "fal.ai",
        "model_id": "fal-ai/kling-video/v1/standard/image-to-video",
        "cost_per_second": 0.10,
        "cost_per_gen": 0.50,
        "max_duration": 10.0,
        "quality": 3,
        "speed": "~60s",
        "resolution": "1280x720",
        "tier": 1,
        "supports_i2v": True,
        "description": "Kling v1 standard — solid baseline quality",
    },
    {
        "id": "kling-v1-5-pro",
        "name": "Kling v1.5 Pro",
        "provider": "fal.ai",
        "model_id": "fal-ai/kling-video/v1.5/pro/image-to-video",
        "cost_per_second": 0.15,
        "cost_per_gen": 0.75,
        "max_duration": 10.0,
        "quality": 5,
        "speed": "~90s",
        "resolution": "1920x1080",
        "tier": 1,
        "supports_i2v": True,
        "description": "Kling v1.5 Pro — highest fidelity, best for hero content",
    },
    {
        "id": "kling-v2",
        "name": "Kling v2 Master",
        "provider": "fal.ai",
        "model_id": "fal-ai/kling-video/v2/master/image-to-video",
        "cost_per_second": 0.18,
        "cost_per_gen": 0.90,
        "max_duration": 10.0,
        "quality": 5,
        "speed": "~120s",
        "resolution": "1920x1080",
        "tier": 1,
        "supports_i2v": True,
        "description": "Kling v2 Master — latest generation, top-tier motion coherence",
    },
    {
        "id": "minimax",
        "name": "MiniMax Video-01",
        "provider": "fal.ai",
        "model_id": "fal-ai/minimax/video-01/image-to-video",
        "cost_per_second": 0.05,
        "cost_per_gen": 0.30,
        "max_duration": 6.0,
        "quality": 4,
        "speed": "~45s",
        "resolution": "1280x720",
        "tier": 1,
        "supports_i2v": True,
        "description": "MiniMax Video-01 — excellent prompt adherence and motion",
    },
    {
        "id": "minimax-live",
        "name": "MiniMax Live",
        "provider": "fal.ai",
        "model_id": "fal-ai/minimax/video-01-live/image-to-video",
        "cost_per_second": 0.04,
        "cost_per_gen": 0.24,
        "max_duration": 6.0,
        "quality": 4,
        "speed": "~30s",
        "resolution": "1280x720",
        "tier": 1,
        "supports_i2v": True,
        "description": "MiniMax Live — fast variant, great for real-time workflows",
    },
    # Tier 2 — Good quality
    {
        "id": "wan2.1-480p",
        "name": "Wan 2.1 480p",
        "provider": "fal.ai",
        "model_id": "fal-ai/wan/v2.1/image-to-video/480p",
        "cost_per_second": 0.03,
        "cost_per_gen": 0.15,
        "max_duration": 5.0,
        "quality": 3,
        "speed": "~30s",
        "resolution": "848x480",
        "tier": 2,
        "supports_i2v": True,
        "description": "Wan 2.1 480p — budget-friendly, fast turnaround",
    },
    {
        "id": "wan2.1-720p",
        "name": "Wan 2.1 720p",
        "provider": "fal.ai",
        "model_id": "fal-ai/wan/v2.1/image-to-video/720p",
        "cost_per_second": 0.05,
        "cost_per_gen": 0.25,
        "max_duration": 5.0,
        "quality": 4,
        "speed": "~45s",
        "resolution": "1280x720",
        "tier": 2,
        "supports_i2v": True,
        "description": "Wan 2.1 720p — good balance of cost and quality",
    },
    {
        "id": "wan2.1-1080p",
        "name": "Wan 2.1 1080p",
        "provider": "fal.ai",
        "model_id": "fal-ai/wan/v2.1/image-to-video/1080p",
        "cost_per_second": 0.08,
        "cost_per_gen": 0.40,
        "max_duration": 5.0,
        "quality": 4,
        "speed": "~75s",
        "resolution": "1920x1080",
        "tier": 2,
        "supports_i2v": True,
        "description": "Wan 2.1 1080p — full HD output",
    },
    {
        "id": "runway-gen3",
        "name": "Runway Gen-3 Turbo",
        "provider": "fal.ai",
        "model_id": "fal-ai/runway-gen3/turbo/image-to-video",
        "cost_per_second": 0.10,
        "cost_per_gen": 0.50,
        "max_duration": 10.0,
        "quality": 4,
        "speed": "~60s",
        "resolution": "1280x768",
        "tier": 2,
        "supports_i2v": True,
        "description": "Runway Gen-3 Alpha Turbo — cinematic motion quality",
    },
    # Tier 3 — Budget / Fast
    {
        "id": "luma-ray2",
        "name": "Luma Ray 2",
        "provider": "fal.ai",
        "model_id": "fal-ai/luma-dream-machine/ray-2/image-to-video",
        "cost_per_second": 0.04,
        "cost_per_gen": 0.20,
        "max_duration": 9.0,
        "quality": 3,
        "speed": "~25s",
        "resolution": "1280x720",
        "tier": 3,
        "supports_i2v": True,
        "description": "Luma Ray 2 — fast generation, decent quality for previews",
    },
    {
        "id": "pika-2",
        "name": "Pika 2",
        "provider": "fal.ai",
        "model_id": "fal-ai/pika/v2/image-to-video",
        "cost_per_second": 0.04,
        "cost_per_gen": 0.20,
        "max_duration": 5.0,
        "quality": 3,
        "speed": "~30s",
        "resolution": "1024x576",
        "tier": 3,
        "supports_i2v": True,
        "description": "Pika 2 — stylized output, good for abstract visuals",
    },
    {
        "id": "cogvideox",
        "name": "CogVideoX 5B",
        "provider": "fal.ai",
        "model_id": "fal-ai/cogvideox-5b/image-to-video",
        "cost_per_second": 0.02,
        "cost_per_gen": 0.12,
        "max_duration": 6.0,
        "quality": 2,
        "speed": "~40s",
        "resolution": "720x480",
        "tier": 3,
        "supports_i2v": True,
        "description": "CogVideoX 5B — open-source, cheapest option available",
    },
    # Google Veo — Premium cinematic video
    {
        "id": "veo2",
        "name": "Google Veo 2",
        "provider": "fal.ai",
        "model_id": "fal-ai/veo2/image-to-video",
        "cost_per_second": 0.50,
        "cost_per_gen": 2.50,
        "max_duration": 8.0,
        "quality": 5,
        "speed": "~90s",
        "resolution": "1280x720",
        "tier": 1,
        "supports_i2v": True,
        "description": "Google Veo 2 — cinematic motion with physics-based realism",
    },
    {
        "id": "veo3",
        "name": "Google Veo 3 Fast",
        "provider": "fal.ai",
        "model_id": "fal-ai/veo3/fast/image-to-video",
        "cost_per_second": 0.60,
        "cost_per_gen": 3.00,
        "max_duration": 8.0,
        "quality": 5,
        "speed": "~120s",
        "resolution": "1280x720",
        "tier": 1,
        "supports_i2v": True,
        "description": "Google Veo 3 Fast — most advanced video generation with native audio",
    },
]

# ── Image generation models ───────────────────────────────────────────────
IMAGE_MODELS = [
    {
        "id": "fal-ai/flux-lora",
        "name": "Flux LoRA",
        "provider": "fal.ai",
        "cost_per_image": 0.03,
        "cost_per_gen": 0.03,
        "quality": 5,
        "speed": "~8s",
        "resolution": "1024x1024",
        "description": "Brand-trained LoRA for consistent style",
    },
    {
        "id": "fal-ai/flux/schnell",
        "name": "Flux Schnell",
        "provider": "fal.ai",
        "cost_per_image": 0.003,
        "cost_per_gen": 0.003,
        "quality": 2,
        "speed": "~2s",
        "resolution": "1024x1024",
        "description": "Ultra-fast drafts for previewing prompts",
    },
    # Google Imagen — High-quality image generation
    {
        "id": "fal-ai/imagen3",
        "name": "Google Imagen 3",
        "provider": "fal.ai",
        "cost_per_image": 0.05,
        "cost_per_gen": 0.05,
        "quality": 5,
        "speed": "~10s",
        "resolution": "1024x1024",
        "description": "Google Imagen 3 — photorealistic quality, excellent text rendering",
    },
    {
        "id": "fal-ai/imagen3/fast",
        "name": "Google Imagen 3 Fast",
        "provider": "fal.ai",
        "cost_per_image": 0.025,
        "cost_per_gen": 0.025,
        "quality": 4,
        "speed": "~4s",
        "resolution": "1024x1024",
        "description": "Google Imagen 3 Fast — quick high-quality keyframes",
    },
]


@router.get("")
def list_models():
    """Return all available models with default status annotated."""
    default_video = get_setting("default_video_model", VIDEO_MODELS[0]["id"])
    default_image = get_setting("default_image_model", IMAGE_MODELS[0]["id"])

    video_out = []
    for m in VIDEO_MODELS:
        out = {**m, "is_default": m["id"] == default_video}
        video_out.append(out)

    image_out = []
    for m in IMAGE_MODELS:
        out = {**m, "is_default": m["id"] == default_image}
        image_out.append(out)

    return {
        "video_models": video_out,
        "image_models": image_out,
    }


@router.get("/default")
def get_default_model():
    video = get_setting("default_video_model", VIDEO_MODELS[0]["id"])
    image = get_setting("default_image_model", IMAGE_MODELS[0]["id"])
    return {"video_model": video, "image_model": image}


@router.put("/default")
def set_default_model(video_model: str = "", image_model: str = ""):
    if video_model:
        set_setting("default_video_model", video_model)
    if image_model:
        set_setting("default_image_model", image_model)
    return get_default_model()
