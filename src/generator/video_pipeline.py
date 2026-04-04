"""
Full-song AI video generation pipeline.

Replaces the old animated-still-image approach with real AI video generation.
Generates a complete video for an entire song by:

1. Breaking the song into sections based on phrase analysis
2. Generating a keyframe image per section (for visual consistency)
3. Using an AI video model to animate each keyframe into a video segment
4. Chaining segments by using the last frame of segment N as input for segment N+1
5. Stitching all segments into one continuous video matching the exact audio duration

Supported video models (image-to-video, all via fal.ai):
- Tier 1: kling-v1, kling-v1-5-pro, kling-v2, minimax, minimax-live
- Tier 2: wan2.1-480p, wan2.1-720p, wan2.1-1080p, runway-gen3
- Tier 3: luma-ray2, pika-2, cogvideox

Output: H.264 MP4, later encoded to DXV for Resolume.
"""
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost safety constants
# ---------------------------------------------------------------------------

# Hard cost cap per song (USD). Generation stops when this is reached.
MAX_COST_PER_SONG = 30.0

# Models that are too expensive for full-song generation.
# Will raise an error if estimated cost exceeds EXPENSIVE_MODEL_MAX_COST.
EXPENSIVE_MODELS = {"veo2", "veo3"}
EXPENSIVE_MODEL_MAX_COST = 50.0  # USD — refuse if estimated cost exceeds this

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
FAL_KEY = os.environ.get("FAL_KEY", "")
REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")


@dataclass
class VideoGenerationConfig:
    """Configuration for full-song video generation."""

    width: int = 1920
    height: int = 1080
    fps: int = 60
    video_model: str = "kling-v1"  # kling-v1, kling-v1-5, minimax, runway-gen3, wan2.1
    image_model: str = "dall-e-3"  # For keyframe generation
    style_prompt: str = ""  # Overall visual style
    quality: str = "high"  # draft, standard, high
    # API backends
    fal_key: str = ""
    replicate_token: str = ""
    openai_key: str = ""
    # Working directory for intermediate files
    work_dir: str = ""
    # Crossfade duration between segments (seconds)
    crossfade_duration: float = 0.5
    # Max concurrent API calls
    max_concurrent: int = 2
    # Hard cost cap per song (USD). 0 = use global MAX_COST_PER_SONG default.
    max_cost: float = 0.0


# ---------------------------------------------------------------------------
# Supported video models
# ---------------------------------------------------------------------------

SUPPORTED_VIDEO_MODELS = {
    # ── Tier 1 — Best quality ──────────────────────────────────────────────
    "kling-v1": {
        "provider": "fal",
        "model_id": "fal-ai/kling-video/v1/standard/image-to-video",
        "max_duration": 10,
        "cost_per_sec": 0.10,
        "default_resolution": "1280x720",
        "supports_i2v": True,
        "tier": 1,
        "description": "Kling v1 standard — solid baseline quality",
    },
    "kling-v1-5-pro": {
        "provider": "fal",
        "model_id": "fal-ai/kling-video/v1.5/pro/image-to-video",
        "max_duration": 10,
        "cost_per_sec": 0.15,
        "default_resolution": "1920x1080",
        "supports_i2v": True,
        "tier": 1,
        "description": "Kling v1.5 Pro — highest fidelity, best for hero content",
    },
    "kling-v2": {
        "provider": "fal",
        "model_id": "fal-ai/kling-video/v2/master/image-to-video",
        "max_duration": 10,
        "cost_per_sec": 0.18,
        "default_resolution": "1920x1080",
        "supports_i2v": True,
        "tier": 1,
        "description": "Kling v2 Master — latest generation, top-tier motion",
    },
    "minimax": {
        "provider": "fal",
        "model_id": "fal-ai/minimax/video-01/image-to-video",
        "max_duration": 6,
        "cost_per_sec": 0.05,
        "default_resolution": "1280x720",
        "supports_i2v": True,
        "tier": 1,
        "description": "MiniMax Video-01 — excellent prompt adherence",
    },
    "minimax-live": {
        "provider": "fal",
        "model_id": "fal-ai/minimax/video-01-live/image-to-video",
        "max_duration": 6,
        "cost_per_sec": 0.04,
        "default_resolution": "1280x720",
        "supports_i2v": True,
        "tier": 1,
        "description": "MiniMax Live — fast variant, great for real-time workflows",
    },

    # ── Tier 2 — Good quality ─────────────────────────────────────────────
    "wan2.1-480p": {
        "provider": "fal",
        "model_id": "fal-ai/wan/v2.1/image-to-video/480p",
        "max_duration": 5,
        "cost_per_sec": 0.03,
        "default_resolution": "848x480",
        "supports_i2v": True,
        "tier": 2,
        "description": "Wan 2.1 480p — budget-friendly, fast turnaround",
    },
    "wan2.1-720p": {
        "provider": "fal",
        "model_id": "fal-ai/wan/v2.1/image-to-video/720p",
        "max_duration": 5,
        "cost_per_sec": 0.05,
        "default_resolution": "1280x720",
        "supports_i2v": True,
        "tier": 2,
        "description": "Wan 2.1 720p — good balance of cost and quality",
    },
    "wan2.1-1080p": {
        "provider": "fal",
        "model_id": "fal-ai/wan/v2.1/image-to-video/1080p",
        "max_duration": 5,
        "cost_per_sec": 0.08,
        "default_resolution": "1920x1080",
        "supports_i2v": True,
        "tier": 2,
        "description": "Wan 2.1 1080p — full HD output from Wan",
    },
    "runway-gen3": {
        "provider": "fal",
        "model_id": "fal-ai/runway-gen3/turbo/image-to-video",
        "max_duration": 10,
        "cost_per_sec": 0.10,
        "default_resolution": "1280x768",
        "supports_i2v": True,
        "tier": 2,
        "description": "Runway Gen-3 Alpha Turbo — cinematic motion",
    },

    # ── Tier 3 — Budget / Fast ────────────────────────────────────────────
    "luma-ray2": {
        "provider": "fal",
        "model_id": "fal-ai/luma-dream-machine/ray-2/image-to-video",
        "max_duration": 9,
        "cost_per_sec": 0.04,
        "default_resolution": "1280x720",
        "supports_i2v": True,
        "tier": 3,
        "description": "Luma Ray 2 — fast generation, decent quality",
    },
    "pika-2": {
        "provider": "fal",
        "model_id": "fal-ai/pika/v2/image-to-video",
        "max_duration": 5,
        "cost_per_sec": 0.04,
        "default_resolution": "1024x576",
        "supports_i2v": True,
        "tier": 3,
        "description": "Pika 2 — stylized output, good for abstract visuals",
    },
    "cogvideox": {
        "provider": "fal",
        "model_id": "fal-ai/cogvideox-5b/image-to-video",
        "max_duration": 6,
        "cost_per_sec": 0.02,
        "default_resolution": "720x480",
        "supports_i2v": True,
        "tier": 3,
        "description": "CogVideoX 5B — open-source, cheapest option",
    },

    # ── Google Veo — Premium cinematic video ──────────────────────────────
    "veo2": {
        "provider": "fal",
        "model_id": "fal-ai/veo2/image-to-video",
        "max_duration": 8,
        "cost_per_sec": 0.50,
        "default_resolution": "1280x720",
        "supports_i2v": True,
        "tier": 1,
        "description": "Google Veo 2 — cinematic motion with physics-based realism",
    },
    "veo3": {
        "provider": "fal",
        "model_id": "fal-ai/veo3/fast/image-to-video",
        "max_duration": 8,
        "cost_per_sec": 0.60,
        "default_resolution": "1280x720",
        "supports_i2v": True,
        "tier": 1,
        "description": "Google Veo 3 Fast — most advanced video generation with native audio",
    },
}


# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------

# Motion guidance per phrase label
_MOTION_BY_LABEL = {
    "drop": (
        "energetic dynamic motion, rapid camera movements, explosive visual transitions, "
        "pulsing rhythmic energy, stroboscopic flashes of light"
    ),
    "buildup": (
        "gradually accelerating motion, rising tension, camera slowly pushing forward, "
        "increasing visual complexity, building anticipation"
    ),
    "breakdown": (
        "smooth continuous camera movement, slow graceful motion, floating ethereal drift, "
        "gentle panning, breathing space"
    ),
    "intro": (
        "slow reveal, emerging from darkness, gentle fade-in motion, "
        "establishing atmosphere, subtle movement"
    ),
    "outro": (
        "gradual deceleration, fading motion, pulling away, "
        "dissolving into stillness, gentle retreat"
    ),
}

# Mood quadrant visual palettes
_MOOD_VISUALS = {
    "euphoric": (
        "vibrant warm colors, golden light, prismatic refractions, "
        "radiant glow, explosive color bursts"
    ),
    "tense": (
        "deep reds and blacks, harsh shadows, angular forms, "
        "high contrast lighting, electric sparks"
    ),
    "melancholic": (
        "desaturated cool tones, deep blues and grays, soft shadows, "
        "rain-like particles, muted ethereal light"
    ),
    "serene": (
        "soft pastels, gentle ambient light, flowing organic shapes, "
        "warm diffused glow, calm water reflections"
    ),
}

# Professional VJ baseline characteristics
_VJ_BASELINE = (
    "volumetric lighting, depth of field, fluid motion, cinematic quality, "
    "seamless looping visual, professional VJ content, 4K detail, "
    "no text, no watermarks, no human faces"
)


def build_segment_prompt(
    mood_descriptor: str,
    mood_quadrant: str,
    phrase_label: str,
    energy: float,
    style_prompt: str,
    segment_index: int,
    total_segments: int,
) -> str:
    """Build a rich prompt for one video segment.

    Combines mood, phrase structure, energy level, and style into a
    prompt optimized for image-to-video AI models.

    Args:
        mood_descriptor: Human-readable mood (e.g. "euphoric festival energy").
        mood_quadrant: Russell quadrant (euphoric/tense/melancholic/serene).
        phrase_label: Song structure label (drop/buildup/breakdown/intro/outro).
        energy: Normalized energy level 0-1.
        style_prompt: User-supplied visual style description.
        segment_index: Which segment this is (0-based).
        total_segments: Total number of segments in the song.

    Returns:
        A detailed prompt string for AI generation.
    """
    parts = []

    # Style prompt takes priority
    if style_prompt:
        parts.append(style_prompt)

    # Mood-based visuals
    mood_visual = _MOOD_VISUALS.get(mood_quadrant, "")
    if mood_visual:
        parts.append(mood_visual)

    # Mood descriptor from analysis
    if mood_descriptor:
        parts.append(f"{mood_descriptor} atmosphere")

    # Motion guidance from phrase label
    motion = _MOTION_BY_LABEL.get(phrase_label, _MOTION_BY_LABEL["breakdown"])
    parts.append(motion)

    # Energy intensity modifier
    if energy > 0.8:
        parts.append("maximum intensity, overwhelming visual power")
    elif energy > 0.6:
        parts.append("high energy, strong visual presence")
    elif energy > 0.4:
        parts.append("moderate energy, balanced motion")
    elif energy > 0.2:
        parts.append("low energy, subtle movement")
    else:
        parts.append("minimal energy, near stillness, ambient texture")

    # Professional VJ baseline
    parts.append(_VJ_BASELINE)

    return ", ".join(parts)


def build_keyframe_prompt(
    mood_descriptor: str,
    mood_quadrant: str,
    phrase_label: str,
    energy: float,
    style_prompt: str,
) -> str:
    """Build a prompt for keyframe image generation (DALL-E 3 / Flux).

    Keyframe prompts focus on composition and color rather than motion,
    since they produce still images that will be animated.
    """
    parts = []

    if style_prompt:
        parts.append(style_prompt)

    mood_visual = _MOOD_VISUALS.get(mood_quadrant, "")
    if mood_visual:
        parts.append(mood_visual)

    if mood_descriptor:
        parts.append(f"{mood_descriptor} feeling")

    # Composition guidance based on phrase label
    if phrase_label == "drop":
        parts.append("bold dramatic composition, central focal point, vivid detail")
    elif phrase_label == "buildup":
        parts.append("dynamic composition with leading lines, tension, anticipation")
    elif phrase_label == "breakdown":
        parts.append("open spacious composition, breathing room, atmospheric depth")
    elif phrase_label == "intro":
        parts.append("mysterious emerging composition, depth, negative space")
    elif phrase_label == "outro":
        parts.append("fading composition, dissolving edges, gentle atmosphere")
    else:
        parts.append("balanced abstract composition")

    parts.append(
        "abstract digital art, no text, no watermarks, no human faces, "
        "volumetric lighting, depth of field, ultra detailed, 4K"
    )

    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Segment planning
# ---------------------------------------------------------------------------


def _plan_segments(
    analysis: dict,
    max_segment_duration: float = 10.0,
) -> list[dict]:
    """Plan video segments aligned to phrase boundaries.

    Rules:
    1. Each phrase boundary is ALWAYS a segment boundary
    2. Short phrases (<= max_segment_duration) become one segment
    3. Long phrases (> max_segment_duration) split at beat-quantized points
       WITHIN the phrase
    4. Each segment gets a label based on its phrase type
    5. Splits within a long phrase get a sub_index for prompt variation

    Args:
        analysis: TrackAnalysis.to_dict() output.
        max_segment_duration: Maximum duration per segment (from model spec).

    Returns:
        List of segment dicts with keys:
            start, end, duration, mood_descriptor, mood_quadrant,
            label, energy, segment_index, sub_index
    """
    phrases = analysis.get("phrases", [])
    mood = analysis.get("mood", {})
    mood_descriptor = mood.get("mood_descriptor", "")
    mood_quadrant = mood.get("quadrant", "euphoric")
    bpm = analysis.get("bpm", 128.0)

    if not phrases:
        # Fallback: one segment covering the whole track
        duration = analysis.get("duration", 60.0)
        return [
            {
                "start": 0.0,
                "end": duration,
                "duration": duration,
                "mood_descriptor": mood_descriptor,
                "mood_quadrant": mood_quadrant,
                "label": "drop",
                "energy": 0.5,
                "segment_index": 0,
                "sub_index": 0,
            }
        ]

    segments = []
    beat_duration = 60.0 / bpm

    for phrase in phrases:
        p_start = phrase["start"]
        p_end = phrase["end"]
        p_duration = p_end - p_start
        p_label = phrase.get("label", "buildup")
        p_energy = phrase.get("energy", 0.5)

        if p_duration <= 0:
            continue

        if p_duration <= max_segment_duration:
            # Phrase fits in one segment — use exact phrase boundaries
            segments.append(
                {
                    "start": p_start,
                    "end": p_end,
                    "duration": p_duration,
                    "mood_descriptor": mood_descriptor,
                    "mood_quadrant": mood_quadrant,
                    "label": p_label,
                    "energy": p_energy,
                    "segment_index": len(segments),
                    "sub_index": 0,
                }
            )
        else:
            # Split long phrase into segments of exactly max_segment_duration.
            # Each segment = exactly ONE API call. No sub-chunking.
            # Use max_segment_duration directly (the model's max duration).
            sub_idx = 0
            current = p_start

            while current < p_end - 1.0:  # Don't create tiny tail segments
                seg_end = min(current + max_segment_duration, p_end)

                # Snap to nearest beat boundary for clean transitions
                beats_in = (seg_end - p_start) / beat_duration
                seg_end = p_start + round(beats_in) * beat_duration
                seg_end = min(seg_end, p_end)

                # Ensure we don't create zero-duration segments
                if seg_end <= current:
                    seg_end = min(current + max_segment_duration, p_end)

                seg_dur = seg_end - current
                segments.append(
                    {
                        "start": current,
                        "end": seg_end,
                        "duration": seg_dur,
                        "mood_descriptor": mood_descriptor,
                        "mood_quadrant": mood_quadrant,
                        "label": p_label,
                        "energy": p_energy,
                        "segment_index": len(segments),
                        "sub_index": sub_idx,
                    }
                )
                sub_idx += 1
                current = seg_end

            # Absorb tiny remainder (< 2s) into last segment
            if current < p_end and segments:
                remainder = p_end - current
                if remainder < 2.0:
                    segments[-1]["end"] = p_end
                    segments[-1]["duration"] = p_end - segments[-1]["start"]
                else:
                    # Large enough remainder gets its own segment
                    segments.append(
                        {
                            "start": current,
                            "end": p_end,
                            "duration": remainder,
                            "mood_descriptor": mood_descriptor,
                            "mood_quadrant": mood_quadrant,
                            "label": p_label,
                            "energy": p_energy,
                            "segment_index": len(segments),
                            "sub_index": sub_idx,
                        }
                    )

    # Re-assign segment_index sequentially (in case of any ordering issues)
    for i, seg in enumerate(segments):
        seg["segment_index"] = i

    return segments


# ---------------------------------------------------------------------------
# Keyframe generation (image)
# ---------------------------------------------------------------------------


def _generate_keyframe(
    prompt: str,
    config: VideoGenerationConfig,
    output_path: Optional[Path] = None,
) -> Path:
    """Generate a keyframe image using DALL-E 3.

    Args:
        prompt: Image generation prompt.
        config: Video generation config (for API keys, dimensions).
        output_path: Where to save the image. If None, uses a temp file.

    Returns:
        Path to the generated PNG image.
    """
    api_key = config.openai_key or OPENAI_API_KEY
    if not api_key:
        raise ValueError(
            "No OpenAI API key found. Set OPENAI_API_KEY or pass openai_key in config."
        )

    if output_path is None:
        tmp = tempfile.mkdtemp(prefix="rsv_keyframe_")
        output_path = Path(tmp) / "keyframe.png"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # DALL-E 3 supports 1024x1024, 1024x1792, 1792x1024
    # Map our resolution to closest supported size
    if config.width >= config.height:
        dalle_size = "1792x1024"
    else:
        dalle_size = "1024x1792"

    quality_map = {"draft": "standard", "standard": "standard", "high": "hd"}
    dalle_quality = quality_map.get(config.quality, "standard")

    logger.info(f"Generating keyframe: {dalle_size}, quality={dalle_quality}")
    logger.debug(f"Keyframe prompt: {prompt[:120]}...")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "dall-e-3",
        "prompt": prompt,
        "n": 1,
        "size": dalle_size,
        "quality": dalle_quality,
        "response_format": "url",
    }

    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            "https://api.openai.com/v1/images/generations",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

    image_url = data["data"][0]["url"]

    # Download the image
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        img_resp = client.get(image_url)
        img_resp.raise_for_status()
        output_path.write_bytes(img_resp.content)

    logger.info(f"Keyframe saved: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
    return output_path


# ---------------------------------------------------------------------------
# Video generation (image-to-video)
# ---------------------------------------------------------------------------


def _animate_keyframe_fal(
    keyframe_path: Path,
    prompt: str,
    duration: float,
    config: VideoGenerationConfig,
    model_spec: dict,
) -> Path:
    """Animate a keyframe via fal.ai image-to-video API.

    Uses fal_client for async submission and polling.

    Args:
        keyframe_path: Path to the keyframe image.
        prompt: Motion/animation prompt.
        duration: Desired clip duration in seconds.
        config: Generation config.
        model_spec: Model specification from SUPPORTED_VIDEO_MODELS.

    Returns:
        Path to the downloaded video clip.
    """
    try:
        import fal_client
    except ImportError:
        raise ImportError("fal-client is required for fal.ai models. Install with: pip install fal-client")

    fal_key = config.fal_key or FAL_KEY
    if fal_key:
        os.environ["FAL_KEY"] = fal_key

    model_id = model_spec["model_id"]
    max_dur = model_spec["max_duration"]
    clamped_duration = min(duration, max_dur)

    logger.info(
        f"Animating keyframe via fal.ai: model={model_id}, "
        f"duration={clamped_duration:.1f}s"
    )

    # Upload keyframe image to fal storage
    image_url = fal_client.upload_file(str(keyframe_path))

    # Submit generation request — format duration per model requirements
    model_id = model_spec["model_id"]
    if "veo" in model_id.lower():
        # Veo 2/3 expects duration as '5s', '6s', '7s', or '8s'
        formatted_duration = f"{max(5, min(int(clamped_duration), max_dur))}s"
    elif "kling" in model_id.lower():
        # Kling expects duration as exactly '5' or '10'
        formatted_duration = "5" if clamped_duration <= 7 else "10"
    else:
        formatted_duration = str(int(clamped_duration))

    arguments = {
        "prompt": prompt,
        "image_url": image_url,
        "duration": formatted_duration,
    }

    handle = fal_client.submit(model_id, arguments=arguments)
    result = handle.get()

    # Extract video URL from result
    video_url = None
    if isinstance(result, dict):
        video = result.get("video", {})
        if isinstance(video, dict):
            video_url = video.get("url")
        elif isinstance(video, str):
            video_url = video
        # Some models return output directly
        if not video_url:
            output = result.get("output", {})
            if isinstance(output, dict):
                video_url = output.get("url") or output.get("video_url")
            elif isinstance(output, str):
                video_url = output

    if not video_url:
        raise RuntimeError(f"No video URL in fal.ai response: {result}")

    return _download_video(video_url)


def _animate_keyframe_replicate(
    keyframe_path: Path,
    prompt: str,
    duration: float,
    config: VideoGenerationConfig,
    model_spec: dict,
) -> Path:
    """Animate a keyframe via Replicate image-to-video API.

    Args:
        keyframe_path: Path to the keyframe image.
        prompt: Motion/animation prompt.
        duration: Desired clip duration in seconds.
        config: Generation config.
        model_spec: Model specification from SUPPORTED_VIDEO_MODELS.

    Returns:
        Path to the downloaded video clip.
    """
    token = config.replicate_token or REPLICATE_API_TOKEN
    if not token:
        raise ValueError(
            "No Replicate API token found. Set REPLICATE_API_TOKEN or pass replicate_token in config."
        )

    model_id = model_spec["model_id"]
    max_dur = model_spec["max_duration"]
    clamped_duration = min(duration, max_dur)

    logger.info(
        f"Animating keyframe via Replicate: model={model_id}, "
        f"duration={clamped_duration:.1f}s"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Upload keyframe to a temporary URL via Replicate file API
    with open(keyframe_path, "rb") as f:
        image_data = f.read()

    # Use Replicate's file upload endpoint
    with httpx.Client(timeout=60.0) as client:
        upload_resp = client.post(
            "https://api.replicate.com/v1/files",
            headers={"Authorization": f"Bearer {token}"},
            files={"content": ("keyframe.png", image_data, "image/png")},
        )
        upload_resp.raise_for_status()
        file_url = upload_resp.json().get("urls", {}).get("get", "")

    if not file_url:
        raise RuntimeError("Failed to upload keyframe to Replicate")

    # Build input params
    input_params = {
        "prompt": prompt,
        "image": file_url,
    }

    # Model-specific duration handling
    if "wan" in model_id.lower():
        num_frames = max(16, int(clamped_duration * 16))
        input_params["num_frames"] = num_frames
    else:
        input_params["duration"] = clamped_duration

    create_url = f"https://api.replicate.com/v1/models/{model_id}/predictions"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            create_url,
            json={"input": input_params},
            headers=headers,
        )
        resp.raise_for_status()
        prediction = resp.json()

    prediction_id = prediction.get("id")
    if not prediction_id:
        raise RuntimeError(f"No prediction ID in Replicate response: {prediction}")

    logger.info(f"Replicate prediction created: {prediction_id}")

    # Poll for completion
    poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
    output_url = _poll_replicate(poll_url, headers, timeout=600)

    if not output_url:
        raise RuntimeError(f"Replicate prediction {prediction_id} failed or timed out")

    return _download_video(output_url)


def _poll_replicate(
    poll_url: str,
    headers: dict,
    timeout: float = 600,
    interval: float = 5.0,
) -> Optional[str]:
    """Poll a Replicate prediction until completion."""
    deadline = time.time() + timeout

    with httpx.Client(timeout=30.0) as client:
        while time.time() < deadline:
            resp = client.get(poll_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")

            if status == "succeeded":
                output = data.get("output")
                if isinstance(output, list) and output:
                    return output[0]
                elif isinstance(output, str):
                    return output
                logger.error(f"Unexpected Replicate output format: {output}")
                return None
            elif status in ("failed", "canceled"):
                error = data.get("error", "Unknown error")
                logger.error(f"Replicate prediction {status}: {error}")
                return None

            logger.debug(f"Replicate prediction status: {status}")
            time.sleep(interval)

    logger.error(f"Replicate prediction timed out after {timeout}s")
    return None


def _animate_keyframe(
    keyframe_path: Path,
    prompt: str,
    duration: float,
    config: VideoGenerationConfig,
) -> Path:
    """Use AI video model to animate a keyframe image into a video clip.

    Routes to the correct provider (fal.ai or Replicate) based on the
    configured video model.

    Args:
        keyframe_path: Path to the keyframe PNG image.
        prompt: Motion/animation prompt for the video model.
        duration: Desired clip duration in seconds.
        config: Video generation config.

    Returns:
        Path to the generated video clip (MP4).

    Raises:
        ValueError: If the model is not supported.
        RuntimeError: If video generation fails.
    """
    model_name = config.video_model
    if model_name not in SUPPORTED_VIDEO_MODELS:
        raise ValueError(
            f"Unsupported video model '{model_name}'. "
            f"Supported: {list(SUPPORTED_VIDEO_MODELS.keys())}"
        )

    model_spec = SUPPORTED_VIDEO_MODELS[model_name]
    provider = model_spec["provider"]

    if provider == "fal":
        return _animate_keyframe_fal(keyframe_path, prompt, duration, config, model_spec)
    elif provider == "replicate":
        return _animate_keyframe_replicate(keyframe_path, prompt, duration, config, model_spec)
    else:
        raise ValueError(f"Unknown provider '{provider}' for model '{model_name}'")


# ---------------------------------------------------------------------------
# Video utilities (ffmpeg)
# ---------------------------------------------------------------------------


def _download_video(url: str) -> Path:
    """Download a video from URL to a temporary file."""
    tmp_dir = tempfile.mkdtemp(prefix="rsv_vidclip_")
    output_path = Path(tmp_dir) / "clip.mp4"

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)

    size = output_path.stat().st_size
    if size < 1000:
        raise RuntimeError(f"Downloaded video too small ({size} bytes), likely an error")

    logger.info(f"Downloaded video clip: {output_path} ({size / 1024:.0f} KB)")
    return output_path


def _extract_last_frame(video_path: Path, output_path: Optional[Path] = None) -> Path:
    """Extract the last frame of a video for chaining to the next segment.

    Args:
        video_path: Path to the video file.
        output_path: Where to save the frame. If None, uses a temp file.

    Returns:
        Path to the extracted PNG frame.
    """
    if output_path is None:
        tmp_dir = tempfile.mkdtemp(prefix="rsv_frame_")
        output_path = Path(tmp_dir) / "last_frame.png"
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    # Use ffmpeg to extract last frame:
    # sseof seeks from end, -1 means 1 second before end, then grab 1 frame
    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-0.1",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        # Fallback: try without sseof (grab very last frame via filter)
        cmd_fallback = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", "select='eq(n,0)',setpts=N/FRAME_RATE/TB",
            "-frames:v", "1",
            "-q:v", "2",
            "-update", "1",
            str(output_path),
        ]
        # Actually extract last frame via reverse
        cmd_fallback = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", "trim=end_frame=99999,reverse,trim=end_frame=1,reverse",
            "-frames:v", "1",
            "-q:v", "2",
            str(output_path),
        ]
        result2 = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=30)
        if result2.returncode != 0:
            raise RuntimeError(
                f"Failed to extract last frame from {video_path}: "
                f"{result.stderr[:200]}"
            )

    if not output_path.exists() or output_path.stat().st_size < 100:
        raise RuntimeError(f"Extracted frame is missing or empty: {output_path}")

    logger.debug(f"Extracted last frame: {output_path}")
    return output_path


def _get_video_duration(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return 0.0


def _stitch_segments(
    segment_paths: list[Path],
    output_path: Path,
    target_duration: float,
    fps: int = 60,
    crossfade_duration: float = 0.5,
) -> Path:
    """Stitch video segments into one continuous video.

    Applies crossfade transitions between consecutive segments, then
    trims or pads the result to match the exact target duration.

    Args:
        segment_paths: Ordered list of video segment file paths.
        output_path: Where to write the final video.
        target_duration: Exact target duration in seconds (audio length).
        fps: Output frame rate.
        crossfade_duration: Duration of crossfade between segments.

    Returns:
        Path to the stitched output video.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not segment_paths:
        raise ValueError("No segments to stitch")

    if len(segment_paths) == 1:
        # Single segment — just re-encode to target duration and fps
        _reencode_video(segment_paths[0], output_path, target_duration, fps)
        return output_path

    # Build ffmpeg concat with crossfade between segments
    # For many segments, concat is more reliable than complex xfade chains
    tmp_dir = tempfile.mkdtemp(prefix="rsv_stitch_")

    try:
        # First: normalize all segments to same fps and resolution
        normalized = []
        for i, seg_path in enumerate(segment_paths):
            norm_path = Path(tmp_dir) / f"norm_{i:04d}.mp4"
            _normalize_segment(seg_path, norm_path, fps)
            normalized.append(norm_path)

        if crossfade_duration > 0 and len(normalized) > 1:
            # Use xfade filter chain for crossfade between segments
            stitched = _xfade_chain(normalized, tmp_dir, fps, crossfade_duration)
        else:
            # Simple concat without crossfade
            stitched = _concat_segments(normalized, tmp_dir)

        # Final: trim/pad to exact target duration
        _reencode_video(stitched, output_path, target_duration, fps)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info(
        f"Stitched {len(segment_paths)} segments -> {output_path} "
        f"(target={target_duration:.1f}s)"
    )
    return output_path


def _normalize_segment(input_path: Path, output_path: Path, fps: int):
    """Re-encode a segment to consistent fps and pixel format."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-an",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to normalize segment: {result.stderr[:300]}")


def _xfade_chain(
    segments: list[Path],
    tmp_dir: str,
    fps: int,
    crossfade_duration: float,
) -> Path:
    """Chain multiple segments with xfade crossfade transitions.

    For N segments, builds N-1 xfade filter stages iteratively (pairs).
    """
    if len(segments) < 2:
        return segments[0]

    current = segments[0]

    for i in range(1, len(segments)):
        next_seg = segments[i]
        output = Path(tmp_dir) / f"xfade_{i:04d}.mp4"

        # Get duration of current accumulated video
        current_dur = _get_video_duration(current)
        if current_dur <= 0:
            current_dur = 10.0  # fallback

        # xfade offset: where the transition starts in the first input
        offset = max(0, current_dur - crossfade_duration)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(current),
            "-i", str(next_seg),
            "-filter_complex",
            f"[0:v][1:v]xfade=transition=fade:duration={crossfade_duration}:offset={offset}[out]",
            "-map", "[out]",
            "-r", str(fps),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-an",
            str(output),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(
                f"xfade failed for segment {i}, falling back to concat: "
                f"{result.stderr[:200]}"
            )
            # Fallback: simple concat of remaining
            remaining = [current] + segments[i:]
            return _concat_segments(remaining, tmp_dir)

        current = output

    return current


def _concat_segments(segments: list[Path], tmp_dir: str) -> Path:
    """Simple concat of video segments via ffmpeg concat demuxer."""
    list_file = Path(tmp_dir) / "concat_list.txt"
    with open(list_file, "w") as f:
        for seg in segments:
            f.write(f"file '{seg}'\n")

    output = Path(tmp_dir) / "concat_output.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-an",
        str(output),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Concat failed: {result.stderr[:300]}")

    return output


def _reencode_video(
    input_path: Path,
    output_path: Path,
    target_duration: float,
    fps: int,
):
    """Re-encode video to exact target duration and fps.

    Trims if too long. If too short, the last frame is held (tpad filter).
    """
    current_dur = _get_video_duration(input_path)

    if current_dur <= 0:
        # Can't determine duration, just copy
        shutil.copy2(input_path, output_path)
        return

    if abs(current_dur - target_duration) < 0.1:
        # Close enough, just re-encode with target fps
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-r", str(fps),
            "-t", str(target_duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output_path),
        ]
    elif current_dur > target_duration:
        # Trim
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-t", str(target_duration),
            "-r", str(fps),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output_path),
        ]
    else:
        # Pad by holding last frame
        pad_duration = target_duration - current_dur
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", f"tpad=stop_mode=clone:stop_duration={pad_duration}",
            "-r", str(fps),
            "-t", str(target_duration),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.warning(f"Re-encode failed, copying source: {result.stderr[:200]}")
        shutil.copy2(input_path, output_path)


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def estimate_cost(
    audio_duration: float,
    config: VideoGenerationConfig,
) -> dict:
    """Estimate the generation cost for a full-song video.

    Each segment = exactly ONE video generation API call (no sub-chunking).
    Segment duration = model's max_duration.

    Args:
        audio_duration: Song duration in seconds.
        config: Video generation config.

    Returns:
        Dict with cost breakdown: video_cost, keyframe_cost, total_cost,
        num_segments, model.
    """
    model_name = config.video_model
    model_spec = SUPPORTED_VIDEO_MODELS.get(model_name)
    if not model_spec:
        return {"error": f"Unknown model: {model_name}"}

    max_dur = model_spec["max_duration"]
    cost_per_sec = model_spec["cost_per_sec"]

    # Each segment = one API call at max_duration seconds
    num_segments = math.ceil(audio_duration / max_dur)

    # Video cost: each segment is one call at max_dur seconds
    video_cost = num_segments * cost_per_sec * max_dur

    # Keyframe cost: first segment gets a DALL-E 3 keyframe, rest use chained frames
    # Only ~10% of segments need fresh keyframes (when chaining fails)
    keyframe_cost_each = 0.08 if config.quality == "high" else 0.04
    # Estimate 1 keyframe per song (chaining handles the rest)
    keyframe_cost = keyframe_cost_each

    total = video_cost + keyframe_cost

    return {
        "model": model_name,
        "provider": model_spec["provider"],
        "audio_duration_sec": audio_duration,
        "num_segments": num_segments,
        "max_segment_duration": max_dur,
        "video_cost": round(video_cost, 2),
        "keyframe_cost": round(keyframe_cost, 2),
        "total_cost": round(total, 2),
        "cost_per_sec": cost_per_sec,
    }


def recommend_model(
    duration_seconds: float,
    max_budget: float = 30.0,
    min_tier: int = 3,
) -> str:
    """Recommend the cheapest model that fits within the budget.

    Args:
        duration_seconds: Song duration in seconds.
        max_budget: Maximum acceptable cost in USD.
        min_tier: Minimum acceptable quality tier (1=best, 3=budget).

    Returns:
        Model name string (key into SUPPORTED_VIDEO_MODELS).
    """
    candidates = []
    for name, spec in SUPPORTED_VIDEO_MODELS.items():
        if spec.get("tier", 3) > min_tier:
            continue
        max_dur = spec["max_duration"]
        num_segments = math.ceil(duration_seconds / max_dur)
        cost = num_segments * spec["cost_per_sec"] * max_dur
        candidates.append((cost, spec.get("tier", 3), name))

    # Sort by cost (ascending), then by tier (ascending = better quality)
    candidates.sort(key=lambda x: (x[0], x[1]))

    for cost, tier, name in candidates:
        if cost <= max_budget:
            return name

    # Nothing fits budget — return the cheapest option regardless
    if candidates:
        return candidates[0][2]
    return "cogvideox"  # absolute cheapest fallback


def validate_model_cost(
    model_name: str,
    duration_seconds: float,
) -> None:
    """Check if a model is safe to use for a given duration. Raises ValueError if not.

    Blocks expensive models (Veo2, Veo3) when estimated cost exceeds the threshold.
    """
    if model_name in EXPENSIVE_MODELS:
        spec = SUPPORTED_VIDEO_MODELS.get(model_name, {})
        max_dur = spec.get("max_duration", 8)
        cost_per_sec = spec.get("cost_per_sec", 0.50)
        num_segments = math.ceil(duration_seconds / max_dur)
        estimated_cost = num_segments * cost_per_sec * max_dur

        if estimated_cost > EXPENSIVE_MODEL_MAX_COST:
            recommended = recommend_model(duration_seconds)
            rec_spec = SUPPORTED_VIDEO_MODELS[recommended]
            rec_segments = math.ceil(duration_seconds / rec_spec["max_duration"])
            rec_cost = rec_segments * rec_spec["cost_per_sec"] * rec_spec["max_duration"]
            raise ValueError(
                f"Model '{model_name}' would cost ${estimated_cost:.0f} for "
                f"{duration_seconds:.0f}s of audio. "
                f"Use '{recommended}' instead (${rec_cost:.0f})."
            )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def generate_full_song_video(
    analysis: dict,
    config: VideoGenerationConfig,
    audio_duration: float,
    output_path: Path,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> Path:
    """Generate a complete video for one song.

    This is the main entry point for the video pipeline. It:
    1. Plans segments based on song structure (phrases)
    2. Generates a keyframe image per segment
    3. Animates keyframes into video clips via AI video model
    4. Chains clips (last frame of segment N becomes input for segment N+1)
    5. Stitches all clips into one continuous video
    6. Trims/pads to exact audio duration

    Args:
        analysis: TrackAnalysis.to_dict() output (with mood data populated).
        config: VideoGenerationConfig controlling models, quality, API keys.
        audio_duration: Exact audio duration in seconds.
        output_path: Where to write the final video file.
        progress_callback: Optional callback(stage, current, total) for progress.
            stage: "plan", "keyframe", "animate", "stitch"
            current: Current item index (1-based)
            total: Total items in this stage

    Returns:
        Path to the final video file (H.264 MP4).

    Raises:
        ValueError: If configuration is invalid.
        RuntimeError: If generation fails.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model_name = config.video_model
    if model_name not in SUPPORTED_VIDEO_MODELS:
        raise ValueError(
            f"Unsupported video model '{model_name}'. "
            f"Supported: {list(SUPPORTED_VIDEO_MODELS.keys())}"
        )

    # --- Pre-generation cost check ---
    # Block expensive models for full songs
    validate_model_cost(model_name, audio_duration)

    # Show estimated cost before starting
    cost_estimate = estimate_cost(audio_duration, config)
    cost_cap = config.max_cost if config.max_cost > 0 else MAX_COST_PER_SONG
    logger.info(
        f"Cost estimate: ${cost_estimate['total_cost']:.2f} "
        f"({cost_estimate['num_segments']} segments x "
        f"${cost_estimate['cost_per_sec']}/s x {cost_estimate['max_segment_duration']}s) "
        f"| Cap: ${cost_cap:.2f}"
    )

    if cost_estimate["total_cost"] > cost_cap:
        recommended = recommend_model(audio_duration, max_budget=cost_cap)
        rec_cost = estimate_cost(audio_duration, VideoGenerationConfig(video_model=recommended))
        raise ValueError(
            f"Estimated cost ${cost_estimate['total_cost']:.2f} exceeds cap "
            f"${cost_cap:.2f}. Use '{recommended}' instead "
            f"(${rec_cost['total_cost']:.2f})."
        )

    model_spec = SUPPORTED_VIDEO_MODELS[model_name]
    max_segment_dur = model_spec["max_duration"]
    mood = analysis.get("mood", {})
    mood_descriptor = mood.get("mood_descriptor", "")
    mood_quadrant = mood.get("quadrant", "euphoric")
    style_prompt = config.style_prompt

    # Set up working directory
    if config.work_dir:
        work_dir = Path(config.work_dir)
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="rsv_pipeline_"))
    work_dir.mkdir(parents=True, exist_ok=True)

    keyframes_dir = work_dir / "keyframes"
    clips_dir = work_dir / "clips"
    keyframes_dir.mkdir(exist_ok=True)
    clips_dir.mkdir(exist_ok=True)

    def _progress(stage: str, current: int, total: int):
        if progress_callback:
            progress_callback(stage, current, total)
        logger.info(f"[{stage}] {current}/{total}")

    # --- Step 1: Plan segments ---
    # Use the model's max_duration as segment length — NO sub-chunking
    _progress("plan", 0, 1)
    segments = _plan_segments(analysis, max_segment_dur)
    total_segments = len(segments)
    logger.info(
        f"Planned {total_segments} segments for {audio_duration:.1f}s audio "
        f"(max {max_segment_dur}s per segment, "
        f"1 API call per segment)"
    )
    _progress("plan", 1, 1)

    # --- Step 2: Generate keyframes and animate ---
    clip_paths: list[Path] = []
    current_keyframe: Optional[Path] = None
    accumulated_cost = 0.0
    video_cost_per_segment = model_spec["cost_per_sec"] * max_segment_dur

    for i, segment in enumerate(segments):
        label = segment["label"]
        energy = segment["energy"]
        seg_duration = segment["duration"]

        # --- Cost cap enforcement ---
        estimated_call_cost = video_cost_per_segment
        if i == 0:
            estimated_call_cost += 0.08  # keyframe generation cost
        if accumulated_cost + estimated_call_cost > cost_cap:
            logger.error(
                f"Cost cap reached: ${accumulated_cost:.2f} / ${cost_cap:.2f}. "
                f"Stopping at segment {i}/{total_segments}. "
                f"Stitching {len(clip_paths)} completed segments."
            )
            break

        # Build prompts
        kf_prompt = build_keyframe_prompt(
            mood_descriptor=mood_descriptor,
            mood_quadrant=mood_quadrant,
            phrase_label=label,
            energy=energy,
            style_prompt=style_prompt,
        )
        anim_prompt = build_segment_prompt(
            mood_descriptor=mood_descriptor,
            mood_quadrant=mood_quadrant,
            phrase_label=label,
            energy=energy,
            style_prompt=style_prompt,
            segment_index=i,
            total_segments=total_segments,
        )

        # Generate or chain keyframe
        _progress("keyframe", i + 1, total_segments)

        if i == 0 or current_keyframe is None:
            # First segment: generate fresh keyframe
            kf_path = keyframes_dir / f"keyframe_{i:04d}.png"
            current_keyframe = _generate_keyframe(kf_prompt, config, kf_path)
            accumulated_cost += 0.08  # DALL-E 3 keyframe cost
        else:
            # Chain: use last frame of previous clip as keyframe
            # This ensures visual continuity between segments
            try:
                chained_kf = keyframes_dir / f"keyframe_{i:04d}_chained.png"
                current_keyframe = _extract_last_frame(clip_paths[-1], chained_kf)
            except RuntimeError:
                logger.warning(
                    f"Failed to extract last frame from segment {i - 1}, "
                    f"generating fresh keyframe"
                )
                kf_path = keyframes_dir / f"keyframe_{i:04d}.png"
                current_keyframe = _generate_keyframe(kf_prompt, config, kf_path)
                accumulated_cost += 0.08

        # Animate keyframe into video clip
        _progress("animate", i + 1, total_segments)
        clip_path = _animate_keyframe(current_keyframe, anim_prompt, seg_duration, config)
        accumulated_cost += video_cost_per_segment

        # Save clip to working directory
        final_clip = clips_dir / f"clip_{i:04d}.mp4"
        shutil.copy2(clip_path, final_clip)
        clip_paths.append(final_clip)

        # Clean up temp files from API downloads
        clip_parent = clip_path.parent
        if str(clip_parent).startswith(tempfile.gettempdir()):
            shutil.rmtree(clip_parent, ignore_errors=True)

    if not clip_paths:
        raise RuntimeError("No video segments were generated (cost cap too low?)")

    # --- Step 3: Stitch segments ---
    _progress("stitch", 0, 1)
    final_video = _stitch_segments(
        clip_paths,
        output_path,
        target_duration=audio_duration,
        fps=config.fps,
        crossfade_duration=config.crossfade_duration,
    )
    _progress("stitch", 1, 1)

    # Log actual cost
    logger.info(
        f"Video generated: {output_path} | "
        f"Segments: {len(clip_paths)}/{total_segments} | "
        f"Accumulated cost: ${accumulated_cost:.2f}"
    )

    return final_video
