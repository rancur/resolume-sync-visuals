"""
AI video generation via text-to-video models on Replicate.

Produces actual animated video clips rather than animated still images.
Supports multiple models with different quality/cost tradeoffs.

Usage:
    clip = generate_video_clip("neon particles flowing", duration_seconds=4.0)
    loop = make_seamless_loop(clip, output, loop_duration=4.0)
"""
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")

# Available text-to-video models (Replicate + fal.ai)
AVAILABLE_VIDEO_MODELS = {
    # Tier 1 — Best quality
    "kling-v2": {
        "id": "fal-ai/kling-video/v2/master/text-to-video",
        "provider": "fal",
        "max_duration": 10,
        "cost": 0.90,
        "default_width": 1920,
        "default_height": 1080,
    },
    "kling-v1-5-pro": {
        "id": "fal-ai/kling-video/v1.5/pro/text-to-video",
        "provider": "fal",
        "max_duration": 10,
        "cost": 0.75,
        "default_width": 1920,
        "default_height": 1080,
    },
    "minimax": {
        "id": "fal-ai/minimax/video-01/text-to-video",
        "provider": "fal",
        "max_duration": 6,
        "cost": 0.30,
        "default_width": 1280,
        "default_height": 720,
    },
    "minimax-live": {
        "id": "fal-ai/minimax/video-01-live/text-to-video",
        "provider": "fal",
        "max_duration": 6,
        "cost": 0.24,
        "default_width": 1280,
        "default_height": 720,
    },
    # Tier 2 — Good quality
    "wan2.1-480p": {
        "id": "fal-ai/wan/v2.1/text-to-video/480p",
        "provider": "fal",
        "max_duration": 5,
        "cost": 0.15,
        "default_width": 848,
        "default_height": 480,
    },
    "wan2.1-720p": {
        "id": "fal-ai/wan/v2.1/text-to-video/720p",
        "provider": "fal",
        "max_duration": 5,
        "cost": 0.25,
        "default_width": 1280,
        "default_height": 720,
    },
    "wan2.1-1080p": {
        "id": "fal-ai/wan/v2.1/text-to-video/1080p",
        "provider": "fal",
        "max_duration": 5,
        "cost": 0.40,
        "default_width": 1920,
        "default_height": 1080,
    },
    "runway-gen3": {
        "id": "fal-ai/runway-gen3/turbo/text-to-video",
        "provider": "fal",
        "max_duration": 10,
        "cost": 0.50,
        "default_width": 1280,
        "default_height": 768,
    },
    # Tier 3 — Budget / Fast
    "luma-ray2": {
        "id": "fal-ai/luma-dream-machine/ray-2/text-to-video",
        "provider": "fal",
        "max_duration": 9,
        "cost": 0.20,
        "default_width": 1280,
        "default_height": 720,
    },
    "pika-2": {
        "id": "fal-ai/pika/v2/text-to-video",
        "provider": "fal",
        "max_duration": 5,
        "cost": 0.20,
        "default_width": 1024,
        "default_height": 576,
    },
    "cogvideox": {
        "id": "fal-ai/cogvideox-5b/text-to-video",
        "provider": "fal",
        "max_duration": 6,
        "cost": 0.12,
        "default_width": 720,
        "default_height": 480,
    },
    # Google Veo — Premium cinematic video
    "veo2": {
        "id": "fal-ai/veo2",
        "provider": "fal",
        "max_duration": 8,
        "cost": 4.00,
        "default_width": 1280,
        "default_height": 720,
    },
    "veo3": {
        "id": "fal-ai/veo3/fast",
        "provider": "fal",
        "max_duration": 8,
        "cost": 4.80,
        "default_width": 1280,
        "default_height": 720,
    },
}


def _resolve_token(replicate_token: str = "") -> str:
    """Resolve the Replicate API token from arg or environment."""
    token = replicate_token or REPLICATE_API_TOKEN
    if not token:
        raise ValueError(
            "No Replicate API token found. Set REPLICATE_API_TOKEN environment variable "
            "or pass replicate_token parameter."
        )
    return token


def _get_model_config(model: str) -> dict:
    """Look up a model by short name or full Replicate ID."""
    # Check short names first
    if model in AVAILABLE_VIDEO_MODELS:
        return AVAILABLE_VIDEO_MODELS[model]

    # Check if it matches a full model ID
    for short_name, cfg in AVAILABLE_VIDEO_MODELS.items():
        if cfg["id"] == model:
            return cfg

    # Unknown model -- return a basic config with the ID as-is
    return {
        "id": model,
        "max_duration": 5,
        "cost": 0.30,
        "default_width": 1280,
        "default_height": 720,
    }


def generate_video_clip(
    prompt: str,
    duration_seconds: float,
    width: int = 1280,
    height: int = 720,
    model: str = "wan-ai/wan2.1-t2v-480p",
    replicate_token: str = "",
) -> Optional[Path]:
    """Generate a video clip using a text-to-video model on Replicate.

    Downloads the result and returns the local path.

    Args:
        prompt: Text description of the video to generate.
        duration_seconds: Desired video duration in seconds.
        width: Video width in pixels.
        height: Video height in pixels.
        model: Model short name (e.g. "wan2.1-480p") or full Replicate ID.
        replicate_token: Replicate API token. Falls back to REPLICATE_API_TOKEN env var.

    Returns:
        Path to the downloaded video file, or None on failure.
    """
    token = _resolve_token(replicate_token)
    model_cfg = _get_model_config(model)
    model_id = model_cfg["id"]

    # Clamp duration to model max
    max_dur = model_cfg.get("max_duration", 5)
    if duration_seconds > max_dur:
        logger.warning(
            f"Requested {duration_seconds}s but {model_id} max is {max_dur}s. Clamping."
        )
        duration_seconds = max_dur

    logger.info(
        f"Generating video: model={model_id}, duration={duration_seconds}s, "
        f"{width}x{height}, prompt={prompt[:80]}..."
    )

    # Create prediction via Replicate HTTP API
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    input_params = {
        "prompt": prompt,
        "width": width,
        "height": height,
    }

    # Model-specific parameter naming
    if "wan" in model_id.lower():
        # Wan models use num_frames; approximate from duration at ~16fps
        num_frames = max(16, int(duration_seconds * 16))
        input_params["num_frames"] = num_frames
    elif "minimax" in model_id.lower():
        input_params["duration"] = int(duration_seconds)
    elif "veo" in model_id.lower():
        # Veo 2/3 expects duration as '5s', '6s', '7s', or '8s'
        input_params["duration"] = f"{max(5, min(int(duration_seconds), 8))}s"
    elif "kling" in model_id.lower():
        # Kling expects duration as exactly '5' or '10'
        input_params["duration"] = "5" if duration_seconds <= 7 else "10"
    else:
        input_params["duration"] = int(duration_seconds)

    create_payload = {
        "version": None,  # Use latest version
        "input": input_params,
    }

    # Use the model endpoint (not version-specific)
    create_url = f"https://api.replicate.com/v1/models/{model_id}/predictions"

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(create_url, json=create_payload, headers=headers)
            resp.raise_for_status()
            prediction = resp.json()

        prediction_id = prediction.get("id")
        if not prediction_id:
            logger.error(f"No prediction ID in response: {prediction}")
            return None

        logger.info(f"Prediction created: {prediction_id}")

        # Poll for completion
        poll_url = f"https://api.replicate.com/v1/predictions/{prediction_id}"
        output_url = _poll_prediction(poll_url, headers, timeout=600)

        if not output_url:
            return None

        # Download the video
        return _download_video(output_url, headers)

    except httpx.HTTPStatusError as e:
        logger.error(f"Replicate API error: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Video generation failed: {e}")
        return None


def _poll_prediction(
    poll_url: str, headers: dict, timeout: float = 600, interval: float = 5.0
) -> Optional[str]:
    """Poll a Replicate prediction until it completes or fails.

    Returns the output URL on success, None on failure/timeout.
    """
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
                else:
                    logger.error(f"Unexpected output format: {output}")
                    return None

            elif status in ("failed", "canceled"):
                error = data.get("error", "Unknown error")
                logger.error(f"Prediction {status}: {error}")
                return None

            logger.debug(f"Prediction status: {status}")
            time.sleep(interval)

    logger.error(f"Prediction timed out after {timeout}s")
    return None


def _download_video(url: str, headers: dict = None) -> Optional[Path]:
    """Download a video from URL to a temporary file.

    Returns the local file path.
    """
    try:
        tmpdir = tempfile.mkdtemp(prefix="rsv_video_")
        output_path = Path(tmpdir) / "generated.mp4"

        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            # Replicate output URLs don't need auth headers
            resp = client.get(url)
            resp.raise_for_status()

            output_path.write_bytes(resp.content)

        if output_path.stat().st_size < 1000:
            logger.error(f"Downloaded video too small ({output_path.stat().st_size} bytes)")
            return None

        logger.info(f"Downloaded video: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
        return output_path

    except Exception as e:
        logger.error(f"Failed to download video: {e}")
        return None


def make_seamless_loop(
    video_path: Path,
    output_path: Path,
    loop_duration: float,
) -> Path:
    """Take a generated video and make it loop seamlessly.

    Uses ffmpeg crossfade on first/last frames to create a smooth transition
    at the loop point.

    Args:
        video_path: Path to the source video.
        output_path: Where to write the looped video.
        loop_duration: Target loop duration in seconds.

    Returns:
        Path to the seamless loop video.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get source video duration via ffprobe
    src_duration = _get_video_duration(video_path)
    if src_duration <= 0:
        logger.warning("Could not determine source video duration, copying as-is")
        shutil.copy2(video_path, output_path)
        return output_path

    # Crossfade duration -- 10-20% of loop, capped at 1 second
    crossfade_dur = min(1.0, loop_duration * 0.15)

    if src_duration < loop_duration + crossfade_dur:
        # Source too short for crossfade -- just trim/copy
        logger.info(f"Source ({src_duration:.1f}s) too short for crossfade, trimming to {loop_duration:.1f}s")
        _trim_video(video_path, output_path, loop_duration)
        return output_path

    # Use ffmpeg xfade filter to crossfade end into beginning
    # Split the video: take from start to (loop_duration + crossfade_dur)
    # Then crossfade the tail back onto the head
    tmp_dir = tempfile.mkdtemp(prefix="rsv_loop_")
    trimmed = Path(tmp_dir) / "trimmed.mp4"

    trim_duration = loop_duration + crossfade_dur
    _trim_video(video_path, trimmed, trim_duration)

    # Create the crossfade loop
    # Split into two parts and crossfade
    offset = loop_duration  # Where the crossfade starts in the first input

    filter_complex = (
        f"[0:v]trim=0:{loop_duration + crossfade_dur},setpts=PTS-STARTPTS[base];"
        f"[0:v]trim={loop_duration}:{loop_duration + crossfade_dur},setpts=PTS-STARTPTS[tail];"
        f"[0:v]trim=0:{crossfade_dur},setpts=PTS-STARTPTS[head];"
        f"[tail][head]xfade=transition=fade:duration={crossfade_dur}:offset=0[blended];"
        f"[base]trim=duration={loop_duration - crossfade_dur},setpts=PTS-STARTPTS[main];"
        f"[main][blended]concat=n=2:v=1:a=0[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(trimmed),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-an",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            logger.warning(f"Crossfade failed, falling back to simple trim: {result.stderr[:200]}")
            _trim_video(video_path, output_path, loop_duration)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"ffmpeg not available or timed out: {e}. Copying source.")
        shutil.copy2(video_path, output_path)

    # Cleanup temp
    shutil.rmtree(tmp_dir, ignore_errors=True)

    return output_path


def apply_beat_sync_effects(
    video_path: Path,
    output_path: Path,
    bpm: float,
    phrase: dict,
    effects: dict,
) -> Path:
    """Apply beat-sync effects to a video clip via ffmpeg.

    Effects applied:
    - Brightness flash on beat hits
    - Zoom pulse on beats

    Args:
        video_path: Source video path.
        output_path: Output video path.
        bpm: Track BPM for beat timing.
        phrase: Phrase metadata dict.
        effects: Effects configuration.

    Returns:
        Path to the processed video.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    beat_duration = 60.0 / bpm
    flash_intensity = effects.get("beat_flash_intensity", 0.3)
    zoom_amount = effects.get("zoom_pulse", 0.03)
    energy = phrase.get("energy", 0.5)

    # Scale effects by energy
    flash_intensity *= energy
    zoom_amount *= energy

    # Build ffmpeg eq filter for periodic brightness flash
    # eq brightness oscillates with beat frequency
    beat_freq = 1.0 / beat_duration
    brightness_expr = f"{flash_intensity}*abs(sin({beat_freq}*PI*t))"

    # Zoom pulse expression
    zoom_expr = f"1+{zoom_amount}*abs(sin({beat_freq}*PI*t))"

    filter_parts = []

    if flash_intensity > 0.01:
        filter_parts.append(f"eq=brightness={brightness_expr}")

    if zoom_amount > 0.005:
        filter_parts.append(f"zoompan=z='{zoom_expr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s='iw'x'ih'")

    if not filter_parts:
        # No effects to apply, just copy
        shutil.copy2(video_path, output_path)
        return output_path

    vf = ",".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-an",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"Beat sync effects failed: {result.stderr[:200]}. Using source.")
            shutil.copy2(video_path, output_path)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("ffmpeg not available. Copying source without effects.")
        shutil.copy2(video_path, output_path)

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


def _trim_video(input_path: Path, output_path: Path, duration: float):
    """Trim a video to the specified duration."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-an",
                str(output_path),
            ],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            # Fallback: just copy
            shutil.copy2(input_path, output_path)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        shutil.copy2(input_path, output_path)
