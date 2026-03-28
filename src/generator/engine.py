"""
AI video generation engine.
Generates visual loops synced to music analysis using AI image/video models.

Architecture:
1. Generate keyframe images using DALL-E 3 or Replicate image models
2. Animate between keyframes using video interpolation
3. Apply beat-sync effects (flash, zoom, color shift) via ffmpeg
4. Create seamless loops

Output: One looping video clip per phrase, at the song's BPM.
"""
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)

# Resolve API keys from environment (use op run to inject)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")


@dataclass
class GenerationConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    style_name: str = "abstract"
    style_config: dict = None
    backend: str = "openai"  # "openai" or "replicate"
    loop_duration_beats: int = 4  # Each loop = N beats
    quality: str = "high"  # "draft", "standard", "high"
    output_dir: str = "output"
    cache_dir: str = ".cache/frames"


def generate_visuals(
    analysis: dict,
    config: GenerationConfig,
    progress_callback=None,
) -> list[dict]:
    """
    Generate visual clips for each phrase of the analyzed track.

    Returns list of clip dicts:
    [{"phrase_idx": 0, "path": "/path/to/clip.mp4", "start": 0.0, "end": 8.0, "label": "intro"}, ...]
    """
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(config.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    bpm = analysis["bpm"]
    beat_duration = 60.0 / bpm
    phrases = analysis["phrases"]
    style = config.style_config or {}
    prompts = style.get("prompts", {})
    colors = style.get("colors", {})
    effects = style.get("effects", {})

    clips = []
    total = len(phrases)

    for i, phrase in enumerate(phrases):
        if progress_callback:
            progress_callback(i, total, f"Generating phrase {i+1}/{total} ({phrase['label']})")

        logger.info(f"Generating visual for phrase {i+1}/{total}: {phrase['label']} "
                     f"(energy={phrase['energy']:.2f})")

        # Get prompt for this phrase type
        prompt = _build_prompt(phrase, prompts, colors, config.style_name)

        # Generate keyframes
        keyframes = _generate_keyframes(
            prompt=prompt,
            phrase=phrase,
            config=config,
            cache_dir=cache_dir,
            phrase_idx=i,
        )

        if not keyframes:
            logger.warning(f"  No keyframes generated for phrase {i}, skipping")
            continue

        # Create animated loop from keyframes
        clip_path = output_dir / f"phrase_{i:03d}_{phrase['label']}.mp4"
        _create_beat_synced_loop(
            keyframes=keyframes,
            output_path=clip_path,
            bpm=bpm,
            phrase=phrase,
            config=config,
            effects=effects,
        )

        clips.append({
            "phrase_idx": i,
            "path": str(clip_path),
            "start": phrase["start"],
            "end": phrase["end"],
            "duration": phrase["end"] - phrase["start"],
            "label": phrase["label"],
            "bpm": bpm,
            "beats": phrase["beats"],
        })

        logger.info(f"  Created: {clip_path.name}")

    return clips


def _build_prompt(phrase: dict, prompts: dict, colors: dict, style_name: str) -> str:
    """Build the image generation prompt based on phrase type and style."""
    label = phrase.get("label", "base")
    base_prompt = prompts.get(label, prompts.get("base", f"{style_name} visual, cinematic, 8k quality"))

    # Modulate based on energy
    energy = phrase.get("energy", 0.5)
    if energy > 0.8:
        base_prompt += ", extremely vibrant, maximum intensity, high contrast"
    elif energy > 0.6:
        base_prompt += ", vibrant colors, dynamic energy"
    elif energy < 0.3:
        base_prompt += ", subdued colors, gentle, minimal"

    # Add color guidance
    primary = colors.get("primary", "#FF00FF")
    secondary = colors.get("secondary", "#00FFFF")
    base_prompt += f", dominant colors {primary} and {secondary}"

    # Add production quality markers
    base_prompt += ", professional VJ content, seamless loop ready, no text, no watermark"

    return base_prompt


def _generate_keyframes(
    prompt: str,
    phrase: dict,
    config: GenerationConfig,
    cache_dir: Path,
    phrase_idx: int,
) -> list[Path]:
    """Generate keyframe images for a phrase."""
    # Number of unique keyframes based on phrase energy
    energy = phrase.get("energy", 0.5)
    n_keyframes = 2 if energy < 0.4 else 3 if energy < 0.7 else 4

    if config.quality == "draft":
        n_keyframes = min(n_keyframes, 2)

    keyframes = []
    for kf_idx in range(n_keyframes):
        # Cache key based on prompt + index
        cache_key = hashlib.md5(f"{prompt}_{phrase_idx}_{kf_idx}".encode()).hexdigest()
        cache_path = cache_dir / f"{cache_key}.png"

        if cache_path.exists():
            logger.debug(f"  Using cached keyframe: {cache_path.name}")
            keyframes.append(cache_path)
            continue

        # Vary the prompt slightly per keyframe for visual movement
        kf_prompt = prompt
        if kf_idx > 0:
            variations = [
                ", slightly different angle",
                ", subtle color shift",
                ", camera slowly moving",
                ", gentle perspective change",
            ]
            kf_prompt += variations[kf_idx % len(variations)]

        # Generate image
        img_path = _generate_image(kf_prompt, config, cache_path)
        if img_path:
            keyframes.append(img_path)
            # Small delay to avoid rate limits
            time.sleep(0.5)

    return keyframes


def _generate_image(prompt: str, config: GenerationConfig, output_path: Path) -> Optional[Path]:
    """Generate a single image using the configured backend."""
    if config.backend == "openai":
        return _generate_image_openai(prompt, config, output_path)
    elif config.backend == "replicate":
        return _generate_image_replicate(prompt, config, output_path)
    else:
        raise ValueError(f"Unknown backend: {config.backend}")


def _generate_image_openai(prompt: str, config: GenerationConfig, output_path: Path) -> Optional[Path]:
    """Generate image via OpenAI DALL-E 3."""
    api_key = OPENAI_API_KEY
    if not api_key:
        logger.error("OPENAI_API_KEY not set")
        return None

    # DALL-E 3 supports 1024x1024, 1024x1792, 1792x1024
    # Use landscape for 16:9-ish output, then we'll crop/resize
    size = "1792x1024"

    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "dall-e-3",
                    "prompt": prompt,
                    "n": 1,
                    "size": size,
                    "quality": "hd" if config.quality == "high" else "standard",
                    "response_format": "url",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            image_url = data["data"][0]["url"]

            # Download image
            img_resp = client.get(image_url)
            img_resp.raise_for_status()

            # Save and resize to target resolution
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(img_resp.content)
                tmp_path = tmp.name

            img = Image.open(tmp_path)
            img = _resize_and_crop(img, config.width, config.height)
            img.save(str(output_path), "PNG")
            os.unlink(tmp_path)

            logger.debug(f"  Generated: {output_path.name}")
            return output_path

    except Exception as e:
        logger.error(f"  OpenAI image generation failed: {e}")
        return None


def _generate_image_replicate(prompt: str, config: GenerationConfig, output_path: Path) -> Optional[Path]:
    """Generate image via Replicate (SDXL or Flux)."""
    api_token = REPLICATE_API_TOKEN
    if not api_token:
        logger.error("REPLICATE_API_TOKEN not set")
        return None

    try:
        import replicate
        client = replicate.Client(api_token=api_token)

        # Use Flux Schnell for fast generation
        output = client.run(
            "black-forest-labs/flux-schnell",
            input={
                "prompt": prompt,
                "num_outputs": 1,
                "aspect_ratio": "16:9",
                "output_format": "png",
                "output_quality": 95,
            },
        )

        if output and len(output) > 0:
            img_url = output[0]
            if hasattr(img_url, 'url'):
                img_url = img_url.url

            with httpx.Client(timeout=60.0) as client:
                img_resp = client.get(str(img_url))
                img_resp.raise_for_status()

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(img_resp.content)
                    tmp_path = tmp.name

            img = Image.open(tmp_path)
            img = _resize_and_crop(img, config.width, config.height)
            img.save(str(output_path), "PNG")
            os.unlink(tmp_path)

            return output_path

    except Exception as e:
        logger.error(f"  Replicate image generation failed: {e}")
        return None


def _resize_and_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize and center-crop image to target dimensions."""
    src_ratio = img.width / img.height
    tgt_ratio = target_w / target_h

    if src_ratio > tgt_ratio:
        # Source is wider — fit height, crop width
        new_h = target_h
        new_w = int(img.width * (target_h / img.height))
    else:
        # Source is taller — fit width, crop height
        new_w = target_w
        new_h = int(img.height * (target_w / img.width))

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center crop
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    return img


def _create_beat_synced_loop(
    keyframes: list[Path],
    output_path: Path,
    bpm: float,
    phrase: dict,
    config: GenerationConfig,
    effects: dict,
):
    """
    Create a looping video clip from keyframes with beat-synced effects.

    Approach:
    1. Cross-dissolve between keyframes at beat intervals
    2. Apply zoom pulse on each beat
    3. Apply brightness flash on downbeats
    4. Ensure seamless loop (last frame dissolves back to first)
    """
    beat_duration = 60.0 / bpm
    fps = config.fps
    loop_beats = config.loop_duration_beats
    loop_duration = loop_beats * beat_duration
    total_frames = int(loop_duration * fps)

    if total_frames < 2:
        total_frames = 2

    # Load keyframe images
    kf_images = []
    for kf_path in keyframes:
        img = Image.open(kf_path).convert("RGB")
        if img.size != (config.width, config.height):
            img = _resize_and_crop(img, config.width, config.height)
        kf_images.append(img)

    if not kf_images:
        return

    # Create frame sequence
    with tempfile.TemporaryDirectory() as tmpdir:
        frames_dir = Path(tmpdir) / "frames"
        frames_dir.mkdir()

        # Beat-sync parameters
        flash_intensity = effects.get("beat_flash_intensity", 0.7)
        motion_blur = effects.get("motion_blur", 0.5)
        zoom_amount = 0.02 + (phrase.get("energy", 0.5) * 0.03)  # 2-5% zoom per beat

        for frame_idx in range(total_frames):
            t = frame_idx / fps  # Time in seconds
            beat_pos = t / beat_duration  # Position in beats (fractional)
            beat_frac = beat_pos % 1.0  # Position within current beat

            # Which keyframes to blend
            kf_progress = (frame_idx / total_frames) * len(kf_images)
            kf_a_idx = int(kf_progress) % len(kf_images)
            kf_b_idx = (kf_a_idx + 1) % len(kf_images)
            blend_alpha = kf_progress % 1.0

            # Cross-dissolve between keyframes
            img_a = kf_images[kf_a_idx]
            img_b = kf_images[kf_b_idx]
            frame = Image.blend(img_a, img_b, blend_alpha)

            # Beat-sync zoom pulse (zoom in on beat, zoom out between)
            zoom_factor = 1.0 + zoom_amount * _beat_pulse(beat_frac)
            if zoom_factor != 1.0:
                frame = _apply_zoom(frame, zoom_factor)

            # Brightness flash on beats
            if flash_intensity > 0:
                flash = _beat_flash(beat_frac) * flash_intensity
                if flash > 0.01:
                    enhancer = ImageEnhance.Brightness(frame)
                    frame = enhancer.enhance(1.0 + flash * 0.5)

            # Subtle motion blur for smoother feel
            if motion_blur > 0.3 and beat_frac > 0.3:
                frame = frame.filter(ImageFilter.GaussianBlur(radius=motion_blur * 0.5))

            # Save frame
            frame_path = frames_dir / f"frame_{frame_idx:06d}.png"
            frame.save(str(frame_path), "PNG")

        # Encode to video with ffmpeg
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%06d.png"),
            "-c:v", "libx264",
            "-preset", "slow" if config.quality == "high" else "medium",
            "-crf", "18" if config.quality == "high" else "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-vf", f"scale={config.width}:{config.height}",
            str(output_path),
        ]

        result = subprocess.run(
            ffmpeg_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.error(f"ffmpeg failed: {result.stderr[:500]}")


def _beat_pulse(beat_frac: float) -> float:
    """
    Generate a pulse curve synced to beat position.
    Sharp attack at beat start (0.0), smooth decay.
    """
    # Exponential decay from beat hit
    return np.exp(-beat_frac * 6.0)


def _beat_flash(beat_frac: float) -> float:
    """
    Generate a brightness flash on the beat.
    Very sharp — only the first ~10% of the beat.
    """
    if beat_frac < 0.1:
        return 1.0 - (beat_frac / 0.1)
    return 0.0


def _apply_zoom(img: Image.Image, factor: float) -> Image.Image:
    """Apply center zoom to image."""
    w, h = img.size
    new_w = int(w * factor)
    new_h = int(h * factor)

    img_zoomed = img.resize((new_w, new_h), Image.LANCZOS)

    # Center crop back to original size
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return img_zoomed.crop((left, top, left + w, top + h))
