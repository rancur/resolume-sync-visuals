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
import math
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

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
    loop_duration_beats: int = 0  # Each loop = N beats (0 = auto based on BPM)
    quality: str = "high"  # "draft", "standard", "high"
    output_dir: str = "output"
    cache_dir: str = ".cache/frames"
    strobe_enabled: bool = False  # White flash frames on beats during drops
    strobe_intensity: float = 0.8  # 0.0-1.0, how bright the strobe flash is


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

    # Auto-detect loop duration if not specified
    if config.loop_duration_beats <= 0:
        config.loop_duration_beats = _auto_loop_beats(bpm)
        logger.info(f"Auto loop duration: {config.loop_duration_beats} beats "
                     f"({config.loop_duration_beats * beat_duration:.1f}s at {bpm:.0f} BPM)")

    clips = []
    total = len(phrases)

    for i, phrase in enumerate(phrases):
        if progress_callback:
            progress_callback(i, total, f"Generating phrase {i+1}/{total} ({phrase['label']})")

        logger.info(f"Generating visual for phrase {i+1}/{total}: {phrase['label']} "
                     f"(energy={phrase['energy']:.2f})")

        # Skip if clip already exists (resume support)
        clip_path = output_dir / f"phrase_{i:03d}_{phrase['label']}.mp4"
        if clip_path.exists() and clip_path.stat().st_size > 1000:
            logger.info(f"  Skipping (exists): {clip_path.name}")
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
            continue

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

    # Separate cached results from work that needs generation
    keyframes = [None] * n_keyframes
    to_generate = []  # list of (kf_idx, kf_prompt, cache_path)

    for kf_idx in range(n_keyframes):
        cache_key = hashlib.md5(f"{prompt}_{phrase_idx}_{kf_idx}".encode()).hexdigest()
        cache_path = cache_dir / f"{cache_key}.png"

        if cache_path.exists():
            logger.debug(f"  Using cached keyframe: {cache_path.name}")
            keyframes[kf_idx] = cache_path
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

        to_generate.append((kf_idx, kf_prompt, cache_path))

    # Generate uncached keyframes in parallel
    if to_generate:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_generate_image, kf_prompt, config, cache_path): kf_idx
                for kf_idx, kf_prompt, cache_path in to_generate
            }
            for future in as_completed(futures):
                kf_idx = futures[future]
                try:
                    img_path = future.result()
                    if img_path:
                        keyframes[kf_idx] = img_path
                except Exception as e:
                    logger.error(f"  Keyframe {kf_idx} generation failed: {e}")

    # Filter out any None entries (failed generations) while preserving order
    return [kf for kf in keyframes if kf is not None]


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

    # Truncate prompt if too long (DALL-E 3 limit is ~4000 chars)
    if len(prompt) > 3500:
        prompt = prompt[:3500]

    max_retries = 2
    for attempt in range(max_retries + 1):
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

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and attempt < max_retries:
                # Content policy or prompt issue — simplify and retry
                logger.warning(f"  DALL-E 400 error, simplifying prompt (attempt {attempt+1})")
                prompt = prompt.split(",")[0] + ", abstract visual art, vibrant colors, 8k quality, VJ content"
                time.sleep(1)
                continue
            logger.error(f"  OpenAI image generation failed: {e}")
            return None
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"  Generation error, retrying ({attempt+1}): {e}")
                time.sleep(2)
                continue
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
    1. Cross-dissolve between keyframes with eased blending
    2. Ken Burns slow pan/zoom on each keyframe for perceived motion
    3. Beat-sync zoom pulse with stronger downbeat emphasis
    4. Phrase-aware color grading (drop/breakdown/buildup)
    5. Vignette, strobe, brightness ramps per phrase type
    6. Ensure seamless loop (last frame dissolves back to first)
    """
    beat_duration = 60.0 / bpm
    fps = config.fps
    loop_beats = config.loop_duration_beats
    loop_duration = loop_beats * beat_duration
    total_frames = int(loop_duration * fps)
    label = phrase.get("label", "base")
    energy = phrase.get("energy", 0.5)

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

    # Pre-compute vignette mask (reused every frame during drops)
    vignette_mask = None
    if label == "drop":
        vignette_mask = _create_vignette_mask(config.width, config.height)

    # Assign random Ken Burns directions per keyframe (deterministic seed)
    kb_params = _assign_ken_burns_params(len(kf_images), phrase_seed=hash(str(phrase)))

    # Create frame sequence
    with tempfile.TemporaryDirectory() as tmpdir:
        frames_dir = Path(tmpdir) / "frames"
        frames_dir.mkdir()

        # Beat-sync parameters
        flash_intensity = effects.get("beat_flash_intensity", 0.7)
        motion_blur = effects.get("motion_blur", 0.5)
        zoom_amount = 0.02 + (energy * 0.03)  # 2-5% zoom per beat

        first_frame = None  # Captured after frame 0 is fully rendered (for loop crossfade)

        for frame_idx in range(total_frames):
            t = frame_idx / fps  # Time in seconds
            beat_pos = t / beat_duration  # Position in beats (fractional)
            beat_frac = beat_pos % 1.0  # Position within current beat
            beat_num = int(beat_pos)  # Which beat we're on (0-indexed)
            is_downbeat = (beat_num % 4 == 0)
            phrase_progress = frame_idx / max(total_frames - 1, 1)  # 0.0 to 1.0

            # --- Keyframe blending with eased cross-dissolve ---
            kf_progress = (frame_idx / total_frames) * len(kf_images)
            kf_a_idx = int(kf_progress) % len(kf_images)
            kf_b_idx = (kf_a_idx + 1) % len(kf_images)
            blend_linear = kf_progress % 1.0
            blend_alpha = _ease_in_out(blend_linear)

            img_a = kf_images[kf_a_idx]
            img_b = kf_images[kf_b_idx]

            # Apply Ken Burns to each keyframe before blending
            kb_a = kb_params[kf_a_idx]
            kb_b = kb_params[kf_b_idx]
            # Progress within this keyframe's segment
            seg_len = total_frames / len(kf_images)
            seg_progress = (frame_idx % seg_len) / max(seg_len - 1, 1)
            seg_progress = min(max(seg_progress, 0.0), 1.0)

            img_a = _apply_ken_burns(img_a, kb_a, seg_progress)
            img_b = _apply_ken_burns(img_b, kb_b, seg_progress)

            frame = Image.blend(img_a, img_b, blend_alpha)

            # --- Beat-sync zoom pulse ---
            if is_downbeat:
                # Downbeats: more dramatic zoom
                zoom_factor = 1.0 + (zoom_amount * 1.8) * _beat_pulse(beat_frac)
            else:
                zoom_factor = 1.0 + zoom_amount * _beat_pulse(beat_frac)
            if zoom_factor != 1.0:
                frame = _apply_zoom(frame, zoom_factor)

            # --- Brightness flash on downbeats ---
            if flash_intensity > 0 and is_downbeat:
                flash = _beat_flash(beat_frac) * flash_intensity
                if flash > 0.01:
                    enhancer = ImageEnhance.Brightness(frame)
                    frame = enhancer.enhance(1.0 + flash * 0.7)

            # --- Off-beat brightness oscillation ---
            if not is_downbeat:
                osc = 0.03 * math.sin(beat_frac * math.pi * 2)
                enhancer = ImageEnhance.Brightness(frame)
                frame = enhancer.enhance(1.0 + osc)

            # --- Phrase-type color grading ---
            frame = _apply_phrase_color_grade(frame, label, energy, phrase_progress)

            # --- Drop vignette ---
            if vignette_mask is not None:
                frame = _apply_vignette(frame, vignette_mask, strength=0.5 + energy * 0.3)

            # --- Buildup progressive brightness ---
            if label == "buildup":
                brightness_ramp = 0.85 + 0.3 * phrase_progress  # 0.85 -> 1.15
                enhancer = ImageEnhance.Brightness(frame)
                frame = enhancer.enhance(brightness_ramp)

            # --- Strobe effect (drops only, on beat) ---
            if config.strobe_enabled and label == "drop":
                strobe_val = _strobe_flash(beat_frac, config.strobe_intensity)
                if strobe_val > 0.01:
                    frame = _apply_strobe(frame, strobe_val)

            # --- Subtle motion blur for smoother feel ---
            if motion_blur > 0.3 and beat_frac > 0.3:
                frame = frame.filter(ImageFilter.GaussianBlur(radius=motion_blur * 0.5))

            # --- Seamless loop crossfade (last ~10% of frames blend back to first) ---
            crossfade_zone = int(total_frames * 0.1)
            if crossfade_zone > 0 and frame_idx >= total_frames - crossfade_zone:
                # first_frame is captured on frame 0 (see below after save)
                if first_frame is not None:
                    # alpha ramps from 0.0 (start of zone) to 1.0 (last frame)
                    frames_into_zone = frame_idx - (total_frames - crossfade_zone)
                    alpha = (frames_into_zone + 1) / crossfade_zone
                    frame = Image.blend(frame, first_frame, alpha)

            # Capture first fully-rendered frame for loop crossfade
            if frame_idx == 0:
                first_frame = frame.copy()

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


# ---------------------------------------------------------------------------
# Auto loop duration
# ---------------------------------------------------------------------------

def _auto_loop_beats(bpm: float) -> int:
    """
    Choose loop duration in beats based on BPM.
    Target: 2-4 second loops for smooth VJ content.

    8 beats = 2 bars in 4/4 — ideal for most EDM:
      128 BPM → 3.75s, 140 BPM → 3.4s, 174 BPM → 2.8s
    """
    if bpm >= 170:
        return 16  # 16 beats @ 174 BPM = 5.5s (DnB needs longer loops)
    elif bpm >= 100:
        return 8   # 8 beats = 2 bars, sweet spot for house/techno/trance
    else:
        return 8   # 8 beats @ 90 BPM = 5.3s


# ---------------------------------------------------------------------------
# Easing helpers
# ---------------------------------------------------------------------------

def _ease_in_out(t: float) -> float:
    """Smooth ease-in-out (cubic Hermite). t in [0,1]."""
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# Beat-sync helpers
# ---------------------------------------------------------------------------

def _beat_pulse(beat_frac: float) -> float:
    """
    Generate a pulse curve synced to beat position.
    Sharp attack at beat start (0.0), smooth decay.
    """
    return np.exp(-beat_frac * 6.0)


def _beat_flash(beat_frac: float) -> float:
    """
    Generate a brightness flash on the beat.
    Very sharp -- only the first ~10% of the beat.
    """
    if beat_frac < 0.1:
        return 1.0 - (beat_frac / 0.1)
    return 0.0


def _strobe_flash(beat_frac: float, intensity: float) -> float:
    """
    Brief white flash at the very start of each beat.
    Duration ~5% of beat. Returns 0.0-1.0 scaled by intensity.
    """
    if beat_frac < 0.05:
        return intensity * (1.0 - beat_frac / 0.05)
    return 0.0


def _apply_strobe(img: Image.Image, strength: float) -> Image.Image:
    """Blend frame toward white by strength (0.0 = no change, 1.0 = full white)."""
    white = Image.new("RGB", img.size, (255, 255, 255))
    return Image.blend(img, white, min(strength, 1.0))


# ---------------------------------------------------------------------------
# Ken Burns (slow pan/zoom for perceived motion)
# ---------------------------------------------------------------------------

def _assign_ken_burns_params(n_keyframes: int, phrase_seed: int) -> list[dict]:
    """
    Assign gentle pan/zoom directions per keyframe.
    Each entry: {"zoom_start", "zoom_end", "pan_x", "pan_y"}
    """
    rng = np.random.RandomState(abs(phrase_seed) % (2**31))
    params = []
    for _ in range(n_keyframes):
        # Gentle zoom range: 1.00-1.06
        z_start = 1.0 + rng.uniform(0.0, 0.02)
        z_end = 1.0 + rng.uniform(0.02, 0.06)
        # Pan offset in pixels (will be scaled by image size later)
        # Range: -0.03 to +0.03 of image dimension
        pan_x = rng.uniform(-0.03, 0.03)
        pan_y = rng.uniform(-0.03, 0.03)
        params.append({
            "zoom_start": z_start,
            "zoom_end": z_end,
            "pan_x": pan_x,
            "pan_y": pan_y,
        })
    return params


def _apply_ken_burns(img: Image.Image, kb: dict, progress: float) -> Image.Image:
    """
    Apply Ken Burns effect: gentle zoom + pan interpolated by progress (0-1).
    Returns cropped image at original size.
    """
    w, h = img.size
    zoom = kb["zoom_start"] + (kb["zoom_end"] - kb["zoom_start"]) * progress
    pan_x = kb["pan_x"] * progress * w
    pan_y = kb["pan_y"] * progress * h

    # Zoomed crop region (centered + pan offset)
    crop_w = w / zoom
    crop_h = h / zoom
    cx = w / 2.0 + pan_x
    cy = h / 2.0 + pan_y

    left = max(cx - crop_w / 2.0, 0)
    top = max(cy - crop_h / 2.0, 0)
    right = min(left + crop_w, w)
    bottom = min(top + crop_h, h)

    # Clamp to avoid going out of bounds
    if right - left < crop_w:
        left = max(right - crop_w, 0)
    if bottom - top < crop_h:
        top = max(bottom - crop_h, 0)

    cropped = img.crop((int(left), int(top), int(right), int(bottom)))
    return cropped.resize((w, h), Image.LANCZOS)


# ---------------------------------------------------------------------------
# Zoom helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Color grading per phrase type
# ---------------------------------------------------------------------------

def _apply_phrase_color_grade(
    img: Image.Image, label: str, energy: float, phrase_progress: float
) -> Image.Image:
    """
    Apply color grading based on phrase type.
    - drop: high contrast + saturation, warm push
    - breakdown: cooler tones, desaturated
    - buildup: progressive color shift (warm tint ramps with progress)
    - intro/outro: neutral with slight desaturation
    """
    if label == "drop":
        # High contrast
        img = ImageEnhance.Contrast(img).enhance(1.15 + energy * 0.15)
        # Boost saturation
        img = ImageEnhance.Color(img).enhance(1.2 + energy * 0.2)
        # Warm push via channel mixing
        img = _tint_image(img, r_gain=1.05, g_gain=1.0, b_gain=0.92)

    elif label == "breakdown":
        # Desaturate
        img = ImageEnhance.Color(img).enhance(0.6 + energy * 0.15)
        # Slight contrast reduction for dreamy feel
        img = ImageEnhance.Contrast(img).enhance(0.9)
        # Cool tint
        img = _tint_image(img, r_gain=0.92, g_gain=0.97, b_gain=1.1)

    elif label == "buildup":
        # Progressive warm shift: starts neutral, ends warm
        warm = 0.02 * phrase_progress
        img = _tint_image(
            img,
            r_gain=1.0 + warm * 2.5,
            g_gain=1.0 + warm * 0.5,
            b_gain=1.0 - warm * 1.5,
        )
        # Slight saturation increase over time
        sat = 1.0 + 0.3 * phrase_progress
        img = ImageEnhance.Color(img).enhance(sat)

    elif label in ("intro", "outro"):
        # Slightly desaturated, neutral
        img = ImageEnhance.Color(img).enhance(0.85)

    return img


def _tint_image(
    img: Image.Image, r_gain: float = 1.0, g_gain: float = 1.0, b_gain: float = 1.0
) -> Image.Image:
    """Apply per-channel gain for color tinting. Fast numpy path."""
    arr = np.array(img, dtype=np.float32)
    arr[:, :, 0] *= r_gain
    arr[:, :, 1] *= g_gain
    arr[:, :, 2] *= b_gain
    np.clip(arr, 0, 255, out=arr)
    return Image.fromarray(arr.astype(np.uint8))


# ---------------------------------------------------------------------------
# Vignette
# ---------------------------------------------------------------------------

def _create_vignette_mask(width: int, height: int) -> Image.Image:
    """
    Pre-compute a radial vignette mask (grayscale).
    Center = white (255), edges = dark.
    """
    cx, cy = width / 2.0, height / 2.0
    max_r = math.sqrt(cx * cx + cy * cy)

    # Build with numpy for speed
    y_coords, x_coords = np.mgrid[0:height, 0:width]
    dist = np.sqrt((x_coords - cx) ** 2 + (y_coords - cy) ** 2)
    # Normalize: 0 at center, 1 at corners
    norm = dist / max_r
    # Vignette curve: darken outer 40%+
    mask = np.clip(1.0 - (norm ** 1.8) * 1.2, 0.0, 1.0)
    mask_u8 = (mask * 255).astype(np.uint8)
    return Image.fromarray(mask_u8, mode="L")


def _apply_vignette(
    img: Image.Image, mask: Image.Image, strength: float = 0.5
) -> Image.Image:
    """
    Darken image edges using pre-computed vignette mask.
    strength: 0.0 = no effect, 1.0 = full vignette.
    """
    # Blend mask toward full-white (no darkening) based on inverse strength
    if strength < 1.0:
        white = Image.new("L", mask.size, 255)
        effective_mask = Image.blend(white, mask, strength)
    else:
        effective_mask = mask

    # Apply: multiply each RGB channel by the mask
    arr = np.array(img, dtype=np.float32)
    m = np.array(effective_mask, dtype=np.float32) / 255.0
    arr[:, :, 0] *= m
    arr[:, :, 1] *= m
    arr[:, :, 2] *= m
    np.clip(arr, 0, 255, out=arr)
    return Image.fromarray(arr.astype(np.uint8))
