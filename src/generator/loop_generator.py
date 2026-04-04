"""
V2 loop-bank video generation architecture.

Instead of generating 24+ unique linear segments, generates 5-10 short LOOPS
(one per phrase type), loops each within its phrase duration, adds beat-sync
effects, and outputs one continuous video.

Architecture:
1. Analyze phrases (intro, buildup, drop, breakdown, outro)
2. Group consecutive same-type phrases
3. Generate ONE keyframe per unique phrase type
4. Animate ONE short loop per phrase type (2-4 bars at song BPM)
5. Loop each within its phrase duration (ffmpeg -stream_loop)
6. Add beat-synced post-processing (brightness flash, zoom pulse)
7. Stitch all phrase sections into one continuous video
8. Crossfade between phrase transitions

Result: One continuous video, but visuals LOOP rhythmically within each phrase.
Generates 5-10 API calls instead of 24+, massively reducing cost while
improving visual quality through rhythmic repetition.
"""
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
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Anti-grid/collage negative prompt — appended to ALL keyframe prompts (#81)
ANTI_GRID_SUFFIX = (
    "single continuous scene, no collage, no grid, no panels, no split screen, "
    "no multiple frames, no tiled layout, no side by side, no montage"
)


# ---------------------------------------------------------------------------
# Section intensity mapping (#79 — extreme section contrast)
# ---------------------------------------------------------------------------

SECTION_INTENSITY = {
    "drop": {
        "prefix": "MAXIMUM INTENSITY, explosive, overwhelming, neon chaos, fast motion, ",
        "flash_intensity": 0.15,
        "zoom_amount": 1.02,
        "energy_floor": 0.8,
    },
    "buildup": {
        "prefix": "building energy, rising tension, accelerating motion, ",
        "flash_intensity": 0.08,
        "zoom_amount": 1.01,
        "energy_floor": 0.5,
    },
    "breakdown": {
        "prefix": "minimal, dark, single element, barely visible, calm void, ",
        "flash_intensity": 0.03,
        "zoom_amount": 1.005,
        "energy_floor": 0.2,
    },
    "intro": {
        "prefix": "emerging from darkness, mysterious reveal, subtle atmosphere, ",
        "flash_intensity": 0.02,
        "zoom_amount": 1.003,
        "energy_floor": 0.15,
    },
    "outro": {
        "prefix": "fading away, dissolving into darkness, peaceful resolution, ",
        "flash_intensity": 0.02,
        "zoom_amount": 1.003,
        "energy_floor": 0.1,
    },
}


@dataclass
class LoopBankConfig:
    """Configuration for loop-bank video generation."""

    width: int = 1920
    height: int = 1080
    fps: int = 30
    video_model: str = "kling-v1-5-pro"
    image_model: str = "flux-lora"
    quality: str = "high"
    fal_key: str = ""
    openai_key: str = ""
    lora_url: str = ""
    work_dir: str = ""
    # Loop settings
    loop_bars: int = 2  # Each loop = N bars (2 bars = 8 beats)
    crossfade_duration: float = 0.5  # Seconds of crossfade between phrase types
    # Prompt weighting (#80 — genre-dominant prompts)
    genre_weight: float = 0.60  # Genre keywords = 60% of prompt
    brand_weight: float = 0.30  # Brand keywords = 30%
    section_weight: float = 0.10  # Section keywords = 10%
    # Keyframe validation (#81)
    validate_keyframes: bool = True
    max_keyframe_retries: int = 2
    # Cost limits
    max_cost: float = 30.0


# ---------------------------------------------------------------------------
# Video model durations (Kling duration settings)
# ---------------------------------------------------------------------------

# Kling duration setting → approximate seconds
KLING_DURATIONS = {
    "5": 5.0,   # ~5 seconds
    "10": 10.0, # ~10 seconds
}


class LoopBankGenerator:
    """V2 video generation: loop-bank architecture.

    For each song:
    1. Analyze phrases (intro, buildup, drop, breakdown, outro)
    2. Group consecutive same-type phrases
    3. Generate ONE keyframe per unique phrase type
    4. Animate ONE short loop per phrase type (2-4 bars at song BPM)
    5. Loop each within its phrase duration (ffmpeg -stream_loop)
    6. Add beat-synced post-processing (brightness flash, zoom pulse)
    7. Stitch all phrase sections into one continuous video
    8. Crossfade between phrase transitions

    Result: One continuous video, but visuals LOOP rhythmically within each phrase.
    """

    def __init__(self, config: LoopBankConfig):
        self.config = config
        self.work_dir = Path(config.work_dir) if config.work_dir else None
        self._cost_total = 0.0

    def generate(
        self,
        analysis: dict,
        brand_config: dict,
        style_override: str = "",
        content_modifier: str = "",
        progress_callback=None,
    ) -> Path:
        """Generate full-song video using loop-bank approach.

        Args:
            analysis: Track analysis dict with phrases, bpm, duration, mood, etc.
            brand_config: Brand YAML config (e.g., example.yaml loaded as dict).
            style_override: Optional style keyword overlay.
            content_modifier: Optional content-based prompt modifier.
            progress_callback: Optional (step, total, message) callback.

        Returns:
            Path to the final continuous video file.
        """
        if self.work_dir is None:
            self.work_dir = Path(tempfile.mkdtemp(prefix="rsv_loopbank_"))
        self.work_dir.mkdir(parents=True, exist_ok=True)

        phrases = analysis.get("phrases", [])
        bpm = analysis.get("bpm", 128.0)
        mood = analysis.get("mood", {})
        genre = analysis.get("genre_hint", "")
        total_duration = analysis.get("duration", 0)

        if not phrases:
            raise ValueError("No phrases found in analysis — cannot generate loop bank")

        # Step 1: Identify unique phrase types
        unique_types = self._get_unique_phrase_types(phrases)
        total_steps = len(unique_types) * 2 + len(phrases) + 2  # keyframes + loops + phrases + stitch + effects
        step = 0

        logger.info(
            f"Loop-bank: {len(unique_types)} unique phrase types from "
            f"{len(phrases)} phrases, {bpm} BPM"
        )

        # Step 2: Calculate loop duration (2 bars at song BPM)
        bar_duration = (60.0 / bpm) * 4  # 4 beats per bar
        loop_duration = bar_duration * self.config.loop_bars

        logger.info(
            f"Loop duration: {loop_duration:.2f}s "
            f"({self.config.loop_bars} bars at {bpm} BPM)"
        )

        # Step 3: Generate ONE keyframe per phrase type
        keyframes = {}
        for ptype, info in unique_types.items():
            step += 1
            if progress_callback:
                progress_callback(step, total_steps, f"Generating keyframe: {ptype}")

            prompt = self._build_keyframe_prompt(
                ptype, info, brand_config, genre, mood,
                style_override, content_modifier,
            )
            keyframe_path = self.work_dir / f"keyframe_{ptype}.png"
            keyframes[ptype] = self._generate_keyframe(prompt, keyframe_path)
            logger.info(f"  Keyframe [{ptype}]: {keyframes[ptype]}")

        # Step 4: Animate ONE short loop per phrase type
        loops = {}
        for ptype, keyframe in keyframes.items():
            step += 1
            if progress_callback:
                progress_callback(step, total_steps, f"Animating loop: {ptype}")

            motion_prompt = self._build_motion_prompt(ptype, brand_config, genre, mood)
            loop_path = self.work_dir / f"loop_{ptype}.mp4"
            loops[ptype] = self._animate_loop(
                keyframe, motion_prompt, loop_duration, loop_path,
            )
            logger.info(f"  Loop [{ptype}]: {loops[ptype]} ({loop_duration:.2f}s)")

        # Step 5: For each phrase, loop the appropriate visual to fill the duration
        phrase_videos = []
        for i, phrase in enumerate(phrases):
            step += 1
            ptype = phrase.get("label", "drop")
            ptype = self._normalize_label(ptype)

            if progress_callback:
                progress_callback(
                    step, total_steps,
                    f"Building phrase {i+1}/{len(phrases)}: {ptype}",
                )

            loop = loops.get(ptype, loops.get("drop", next(iter(loops.values()))))
            phrase_duration = phrase["end"] - phrase["start"]

            if phrase_duration <= 0:
                continue

            # Loop the short clip to fill the phrase duration
            phrase_path = self.work_dir / f"phrase_{i:03d}_{ptype}.mp4"
            self._loop_to_duration(loop, phrase_duration, phrase_path)

            # Add beat-synced effects
            effects_path = self.work_dir / f"phrase_{i:03d}_{ptype}_fx.mp4"
            self._add_beat_effects(phrase_path, bpm, phrase, effects_path)

            phrase_videos.append({
                "path": effects_path,
                "label": ptype,
                "start": phrase["start"],
                "end": phrase["end"],
                "duration": phrase_duration,
            })

        if not phrase_videos:
            raise RuntimeError("No phrase videos generated")

        # Step 6: Stitch all phrases with crossfade transitions
        step += 1
        if progress_callback:
            progress_callback(step, total_steps, "Stitching final video")

        final_path = self.work_dir / "final_loopbank.mp4"
        self._stitch_with_crossfade(phrase_videos, final_path)

        logger.info(
            f"Loop-bank complete: {final_path} "
            f"({len(unique_types)} loops, {len(phrase_videos)} phrases, "
            f"est. cost: ${self._cost_total:.2f})"
        )

        return final_path

    # ------------------------------------------------------------------
    # Phrase analysis
    # ------------------------------------------------------------------

    def _get_unique_phrase_types(self, phrases: list[dict]) -> dict:
        """Identify unique phrase types and their representative properties.

        Returns dict mapping normalized label -> {energy, count, total_duration}.
        """
        unique = {}
        for phrase in phrases:
            label = self._normalize_label(phrase.get("label", "drop"))
            duration = phrase["end"] - phrase["start"]
            energy = phrase.get("energy", 0.5)

            if label not in unique:
                unique[label] = {
                    "energy": energy,
                    "count": 1,
                    "total_duration": duration,
                    "spectral_centroid": phrase.get("spectral_centroid", 3000),
                }
            else:
                unique[label]["count"] += 1
                unique[label]["total_duration"] += duration
                # Use max energy for the type (represents peak)
                unique[label]["energy"] = max(unique[label]["energy"], energy)

        return unique

    def _normalize_label(self, label: str) -> str:
        """Normalize phrase labels to standard set."""
        label_lower = label.lower()
        mapping = {
            "intro": "intro",
            "buildup": "buildup",
            "build": "buildup",
            "drop": "drop",
            "chorus": "drop",
            "peak": "drop",
            "breakdown": "breakdown",
            "bridge": "breakdown",
            "outro": "outro",
            "fade": "outro",
        }
        return mapping.get(label_lower, "buildup")

    # ------------------------------------------------------------------
    # Prompt building (#79 extreme contrast, #80 genre-dominant)
    # ------------------------------------------------------------------

    def _build_keyframe_prompt(
        self,
        phrase_type: str,
        type_info: dict,
        brand_config: dict,
        genre: str,
        mood: dict,
        style_override: str = "",
        content_modifier: str = "",
    ) -> str:
        """Build a keyframe prompt with genre-dominant weighting.

        Prompt composition (#80):
        - 60% genre vocabulary (from config/genres/ and brand genre_modifiers)
        - 30% brand identity (from brand YAML sections + style)
        - 10% section-specific intensity (#79)

        Always appends anti-grid suffix (#81).
        """
        parts = []

        # Section intensity prefix (#79 — extreme contrast)
        section_info = SECTION_INTENSITY.get(phrase_type, SECTION_INTENSITY["buildup"])
        parts.append(section_info["prefix"])

        # Genre vocabulary (60% weight — dominant) (#80)
        genre_fragment = self._get_genre_fragment(genre, phrase_type, brand_config)
        if genre_fragment:
            parts.append(genre_fragment)

        # Brand identity (30% weight)
        brand_sections = brand_config.get("sections", {})
        section_config = brand_sections.get(phrase_type, brand_sections.get("drop", {}))
        section_prompt = section_config.get("prompt", "")
        brand_style = brand_config.get("style", {}).get("base", "")

        if section_prompt:
            parts.append(section_prompt)
        elif brand_style:
            parts.append(brand_style)

        # Mood colors
        mood_quadrant = mood.get("quadrant", "euphoric")
        mood_modifiers = brand_config.get("mood_modifiers", {})
        mood_mod = mood_modifiers.get(mood_quadrant, {})
        if mood_mod.get("colors"):
            parts.append(mood_mod["colors"])

        # Content modifier (lyrics-derived)
        if content_modifier:
            parts.append(content_modifier)

        # Style override
        if style_override:
            parts.append(style_override)

        # Anti-grid suffix (#81)
        parts.append(ANTI_GRID_SUFFIX)

        # Keyframe composition guidance
        parts.append(
            "single perfectly composed frame, dramatic composition, "
            "high detail, sharp focus, suitable as first frame of a smooth video"
        )

        prompt = ", ".join(p.strip() for p in parts if p and p.strip())

        # Truncate if too long
        if len(prompt) > 900:
            prompt = prompt[:900]

        return prompt

    def _build_motion_prompt(
        self,
        phrase_type: str,
        brand_config: dict,
        genre: str,
        mood: dict,
    ) -> str:
        """Build a motion/animation prompt for the video model."""
        sections = brand_config.get("sections", {})
        section = sections.get(phrase_type, {})
        motion = section.get("motion", "")

        # Section-specific motion from brand config
        parts = []
        if motion:
            parts.append(motion)

        # Add intensity-appropriate motion guidance
        section_info = SECTION_INTENSITY.get(phrase_type, SECTION_INTENSITY["buildup"])
        if phrase_type == "drop":
            parts.append("explosive, reality-breaking, kaleidoscopic rotation")
        elif phrase_type == "buildup":
            parts.append("camera accelerating forward, visual density increasing")
        elif phrase_type == "breakdown":
            parts.append("slow floating drift, gentle organic breathing")
        elif phrase_type == "intro":
            parts.append("slow reveal, emerging from darkness")
        elif phrase_type == "outro":
            parts.append("slow fade, settling, dissolving")

        parts.append("seamless looping motion, fluid continuous movement")

        return ", ".join(p for p in parts if p)

    def _get_genre_fragment(
        self,
        genre: str,
        section: str,
        brand_config: dict,
    ) -> str:
        """Get genre vocabulary from config/genres/ YAML and brand modifiers.

        Combines structured genre vocabulary with brand-level genre modifiers
        for a rich genre-specific prompt fragment.
        """
        if not genre:
            return ""

        parts = []

        # Try structured genre vocabulary (from config/genres/*.yaml)
        try:
            from ..analyzer.genre_vocabulary import genre_to_prompt_fragment
            fragment = genre_to_prompt_fragment(genre, section, brand_config=brand_config)
            if fragment:
                parts.append(fragment)
        except Exception:
            pass

        # Brand-level genre modifiers
        genre_modifiers = brand_config.get("genre_modifiers", {})
        genre_lower = genre.lower()
        genre_mod = genre_modifiers.get(genre_lower, {})

        if genre_mod.get("extra"):
            parts.append(genre_mod["extra"])
        if genre_mod.get("pixel_style"):
            parts.append(genre_mod["pixel_style"])

        return ", ".join(p for p in parts if p)

    # ------------------------------------------------------------------
    # Keyframe generation
    # ------------------------------------------------------------------

    def _generate_keyframe(self, prompt: str, output_path: Path) -> Path:
        """Generate a keyframe image via Flux LoRA on fal.ai.

        Includes grid/collage validation (#81) — regenerates if artifacts detected.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Resume support
        if output_path.exists() and output_path.stat().st_size > 1000:
            logger.info(f"  Keyframe exists, skipping: {output_path.name}")
            return output_path

        fal_key = self.config.fal_key or os.environ.get("FAL_KEY", "")
        if not fal_key:
            raise ValueError("FAL_KEY required for keyframe generation")

        os.environ["FAL_KEY"] = fal_key

        try:
            import fal_client
        except ImportError:
            raise ImportError("fal-client required. Install: pip install fal-client")

        model_id = "fal-ai/flux-lora"

        arguments = {
            "prompt": prompt,
            "image_size": {
                "width": self.config.width,
                "height": self.config.height,
            },
            "num_images": 1,
            "output_format": "png",
            "guidance_scale": 3.5,
            "num_inference_steps": 28,
            "enable_safety_checker": False,
        }

        if self.config.lora_url:
            arguments["loras"] = [{"path": self.config.lora_url, "scale": 1.0}]

        retries = 0
        max_retries = self.config.max_keyframe_retries if self.config.validate_keyframes else 0

        while True:
            logger.info(f"  Generating keyframe via Flux LoRA (attempt {retries + 1})")

            handle = fal_client.submit(model_id, arguments=arguments)
            result = handle.get()

            image_url = None
            if isinstance(result, dict):
                images = result.get("images", [])
                if images and isinstance(images[0], dict):
                    image_url = images[0].get("url")

            if not image_url:
                raise RuntimeError(f"No image URL in Flux response: {result}")

            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                img_resp = client.get(image_url)
                img_resp.raise_for_status()
                output_path.write_bytes(img_resp.content)

            self._cost_total += 0.04  # Flux LoRA cost

            # Validate for grid/collage artifacts (#81)
            if self.config.validate_keyframes and retries < max_retries:
                if self._has_grid_artifacts(output_path):
                    logger.warning(
                        f"  Grid/collage detected in keyframe, regenerating "
                        f"(attempt {retries + 2})"
                    )
                    retries += 1
                    # Strengthen anti-grid prompt
                    arguments["prompt"] = (
                        "IMPORTANT: single continuous scene only. "
                        + arguments["prompt"]
                    )
                    continue

            break

        logger.info(
            f"  Keyframe saved: {output_path.name} "
            f"({output_path.stat().st_size / 1024:.0f} KB)"
        )
        return output_path

    def _has_grid_artifacts(self, image_path: Path) -> bool:
        """Check if an image has grid/collage artifacts (#81).

        Looks for multiple distinct rectangular regions that suggest
        the model generated a collage instead of a single scene.

        Uses edge detection to find strong horizontal/vertical lines
        that span most of the image width/height.
        """
        try:
            from PIL import Image, ImageFilter
            import numpy as np

            img = Image.open(image_path).convert("L")  # Grayscale
            w, h = img.size

            # Apply edge detection
            edges = img.filter(ImageFilter.FIND_EDGES)
            edge_array = np.array(edges)

            # Check for strong horizontal lines (grid dividers)
            # A grid artifact creates a horizontal line where brightness changes abruptly
            row_sums = np.mean(edge_array, axis=1)
            threshold = np.mean(row_sums) + 2 * np.std(row_sums)

            strong_h_lines = 0
            # Skip edges (top/bottom 10%)
            margin = int(h * 0.1)
            for y in range(margin, h - margin):
                if row_sums[y] > threshold:
                    # Check if this line spans at least 60% of width
                    line_pixels = edge_array[y, :]
                    bright_pct = np.sum(line_pixels > 128) / w
                    if bright_pct > 0.6:
                        strong_h_lines += 1

            # Check for strong vertical lines
            col_sums = np.mean(edge_array, axis=0)
            threshold_v = np.mean(col_sums) + 2 * np.std(col_sums)

            strong_v_lines = 0
            margin_w = int(w * 0.1)
            for x in range(margin_w, w - margin_w):
                if col_sums[x] > threshold_v:
                    col_pixels = edge_array[:, x]
                    bright_pct = np.sum(col_pixels > 128) / h
                    if bright_pct > 0.6:
                        strong_v_lines += 1

            # If we find both strong H and V lines, it's likely a grid
            is_grid = strong_h_lines >= 1 and strong_v_lines >= 1
            if is_grid:
                logger.debug(
                    f"Grid detected: {strong_h_lines} horizontal, "
                    f"{strong_v_lines} vertical lines"
                )
            return is_grid

        except Exception as e:
            logger.debug(f"Grid detection failed: {e}")
            return False  # If detection fails, assume OK

    # ------------------------------------------------------------------
    # Loop animation
    # ------------------------------------------------------------------

    def _animate_loop(
        self,
        keyframe_path: Path,
        motion_prompt: str,
        loop_duration: float,
        output_path: Path,
    ) -> Path:
        """Animate a keyframe into a short loop via image-to-video API.

        Uses Kling's '5' duration setting (slightly longer than needed),
        then trims to exact bar-aligned length.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Resume support
        if output_path.exists() and output_path.stat().st_size > 10000:
            logger.info(f"  Loop exists, skipping: {output_path.name}")
            return output_path

        fal_key = self.config.fal_key or os.environ.get("FAL_KEY", "")
        if not fal_key:
            raise ValueError("FAL_KEY required for video generation")

        os.environ["FAL_KEY"] = fal_key

        try:
            import fal_client
        except ImportError:
            raise ImportError("fal-client required. Install: pip install fal-client")

        # Determine model and duration setting
        from .video_pipeline import SUPPORTED_VIDEO_MODELS
        model_spec = SUPPORTED_VIDEO_MODELS.get(
            self.config.video_model,
            SUPPORTED_VIDEO_MODELS["kling-v1-5-pro"],
        )
        model_id = model_spec["model_id"]

        # Upload keyframe
        image_url = fal_client.upload_file(str(keyframe_path))

        # Use '5' duration (5 seconds) — trim to exact loop_duration after
        # For most BPMs (100-175), 2 bars = 2.74s to 4.80s, fits in 5s
        duration_setting = "5"
        if loop_duration > 5.0:
            duration_setting = "10"

        arguments = {
            "prompt": motion_prompt,
            "image_url": image_url,
            "duration": duration_setting,
            "aspect_ratio": "16:9",
        }

        logger.info(
            f"  Animating loop via {self.config.video_model} "
            f"(duration={duration_setting}s, target={loop_duration:.2f}s)"
        )

        handle = fal_client.submit(model_id, arguments=arguments)
        result = handle.get()

        # Extract video URL
        video_url = None
        if isinstance(result, dict):
            video_data = result.get("video", {})
            if isinstance(video_data, dict):
                video_url = video_data.get("url")
            # Some models return video directly as URL
            if not video_url and result.get("video_url"):
                video_url = result["video_url"]

        if not video_url:
            raise RuntimeError(f"No video URL in response: {result}")

        # Download raw video
        raw_path = output_path.with_suffix(".raw.mp4")
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            vid_resp = client.get(video_url)
            vid_resp.raise_for_status()
            raw_path.write_bytes(vid_resp.content)

        # Track cost
        cost_per_sec = model_spec.get("cost_per_sec", 0.10)
        gen_duration = float(duration_setting)
        self._cost_total += cost_per_sec * gen_duration

        # Trim to exact loop duration (bar-aligned)
        self._trim_video(raw_path, output_path, loop_duration)

        # Clean up raw
        if raw_path.exists():
            raw_path.unlink()

        return output_path

    # ------------------------------------------------------------------
    # Looping and effects
    # ------------------------------------------------------------------

    def _loop_to_duration(
        self,
        loop_path: Path,
        target_duration: float,
        output_path: Path,
    ) -> Path:
        """Loop a short video clip to fill a target duration.

        Uses ffmpeg -stream_loop for efficient looping.
        """
        output_path = Path(output_path)

        # Get source duration
        src_duration = self._get_duration(loop_path)
        if src_duration <= 0:
            shutil.copy2(loop_path, output_path)
            return output_path

        if src_duration >= target_duration * 0.95:
            # Already long enough — just trim
            self._trim_video(loop_path, output_path, target_duration)
            return output_path

        # Calculate loop count needed
        n_loops = math.ceil(target_duration / src_duration)

        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(n_loops),
            "-i", str(loop_path),
            "-t", str(target_duration),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", str(self.config.fps),
            "-an",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"Loop failed: {result.stderr[:200]}")
            shutil.copy2(loop_path, output_path)

        return output_path

    def _add_beat_effects(
        self,
        video_path: Path,
        bpm: float,
        phrase: dict,
        output_path: Path,
    ) -> Path:
        """Add beat-synced post-processing via ffmpeg.

        Effects:
        - Brightness flash every beat (every 60/BPM seconds)
        - Zoom pulse every bar (every 4 beats)
        - Intensity scaled by section type (#79)
        """
        output_path = Path(output_path)
        label = self._normalize_label(phrase.get("label", "drop"))
        section_info = SECTION_INTENSITY.get(label, SECTION_INTENSITY["buildup"])

        beat_interval = 60.0 / bpm
        flash = section_info["flash_intensity"]
        zoom = section_info["zoom_amount"]

        # Build ffmpeg filter chain
        filters = []

        # Brightness flash every beat
        # Creates a sharp flash at each beat that decays over 10% of the beat interval
        decay = beat_interval * 0.1
        if flash > 0.005:
            # eq filter: brightness oscillation synced to BPM
            # flash = intensity * max(0, 1 - mod(t, beat_interval) / decay)
            # Only flashes in the first 10% of each beat interval
            brightness_expr = (
                f"{flash}*if(lt(mod(t\\,{beat_interval:.6f})\\,{decay:.6f})\\,"
                f"1-mod(t\\,{beat_interval:.6f})/{decay:.6f}\\,0)"
            )
            filters.append(f"eq=brightness='{brightness_expr}'")

        # Zoom pulse every bar (4 beats)
        bar_interval = beat_interval * 4
        if zoom > 1.001:
            zoom_factor = zoom - 1.0
            zoom_decay = bar_interval * 0.15
            # zoompan for periodic zoom pulse
            zoom_expr = (
                f"1+{zoom_factor}*if(lt(mod(t\\,{bar_interval:.6f})\\,{zoom_decay:.6f})\\,"
                f"1-mod(t\\,{bar_interval:.6f})/{zoom_decay:.6f}\\,0)"
            )
            # Use zoompan with the zoom expression
            filters.append(
                f"zoompan=z='{zoom_expr}'"
                f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d=1:s={self.config.width}x{self.config.height}"
                f":fps={self.config.fps}"
            )

        if not filters:
            # No effects needed — just copy
            shutil.copy2(video_path, output_path)
            return output_path

        filter_chain = ",".join(filters)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", filter_chain,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.warning(
                f"Beat effects failed for {label}, using original: "
                f"{result.stderr[:200]}"
            )
            shutil.copy2(video_path, output_path)

        return output_path

    # ------------------------------------------------------------------
    # Stitching
    # ------------------------------------------------------------------

    def _stitch_with_crossfade(
        self,
        phrase_videos: list[dict],
        output_path: Path,
    ) -> Path:
        """Stitch all phrase sections with crossfade transitions.

        - Crossfade between different phrase types
        - No crossfade within same phrase type (seamless loop continues)
        """
        output_path = Path(output_path)

        if len(phrase_videos) == 0:
            raise RuntimeError("No phrase videos to stitch")

        if len(phrase_videos) == 1:
            shutil.copy2(phrase_videos[0]["path"], output_path)
            return output_path

        # Build ffmpeg concat with crossfade transitions
        # For adjacent same-type phrases: direct concat (seamless)
        # For different types: xfade crossfade
        cf_duration = self.config.crossfade_duration

        # Identify transition points
        transitions = []
        for i in range(len(phrase_videos) - 1):
            current_label = phrase_videos[i]["label"]
            next_label = phrase_videos[i + 1]["label"]
            needs_crossfade = current_label != next_label
            transitions.append(needs_crossfade)

        # If no crossfades needed, simple concat
        if not any(transitions):
            return self._simple_concat(phrase_videos, output_path)

        # Use xfade filter for crossfade transitions
        # This requires chaining xfade filters for each transition
        return self._xfade_concat(phrase_videos, transitions, cf_duration, output_path)

    def _simple_concat(
        self,
        phrase_videos: list[dict],
        output_path: Path,
    ) -> Path:
        """Concatenate videos without crossfade (same phrase type)."""
        concat_list = self.work_dir / "concat_list.txt"
        with open(concat_list, "w") as f:
            for pv in phrase_videos:
                f.write(f"file '{pv['path']}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"Concat failed: {result.stderr[:500]}")

        return output_path

    def _xfade_concat(
        self,
        phrase_videos: list[dict],
        transitions: list[bool],
        cf_duration: float,
        output_path: Path,
    ) -> Path:
        """Concatenate with xfade crossfade transitions between different sections.

        Uses ffmpeg xfade filter chain for smooth transitions.
        For many segments, builds a complex filter graph.
        """
        n = len(phrase_videos)

        # For simplicity and reliability, do pairwise concat
        # Start with first video, progressively merge
        current_path = phrase_videos[0]["path"]

        for i in range(n - 1):
            next_path = phrase_videos[i + 1]["path"]
            merged_path = self.work_dir / f"merged_{i:03d}.mp4"

            if transitions[i]:
                # Crossfade transition
                current_dur = self._get_duration(current_path)
                offset = max(0, current_dur - cf_duration)

                cmd = [
                    "ffmpeg", "-y",
                    "-i", str(current_path),
                    "-i", str(next_path),
                    "-filter_complex",
                    f"[0:v][1:v]xfade=transition=fade:duration={cf_duration}:offset={offset}[v]",
                    "-map", "[v]",
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    "-an",
                    str(merged_path),
                ]
            else:
                # Simple concat (same phrase type)
                concat_file = self.work_dir / f"pair_{i:03d}.txt"
                with open(concat_file, "w") as f:
                    f.write(f"file '{current_path}'\n")
                    f.write(f"file '{next_path}'\n")

                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_file),
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    "-an",
                    str(merged_path),
                ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                logger.warning(f"Merge step {i} failed: {result.stderr[:200]}")
                # Fallback: just concat without crossfade
                concat_file = self.work_dir / f"pair_{i:03d}_fb.txt"
                with open(concat_file, "w") as f:
                    f.write(f"file '{current_path}'\n")
                    f.write(f"file '{next_path}'\n")
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_file),
                    "-c", "copy", "-an",
                    str(merged_path),
                ]
                subprocess.run(cmd, capture_output=True, text=True, timeout=300)

            current_path = merged_path

        # Final copy
        shutil.copy2(current_path, output_path)
        return output_path

    # ------------------------------------------------------------------
    # FFmpeg helpers
    # ------------------------------------------------------------------

    def _trim_video(
        self,
        input_path: Path,
        output_path: Path,
        duration: float,
    ):
        """Trim video to exact duration."""
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", str(self.config.fps),
            "-an",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"Trim failed: {result.stderr[:200]}")
            shutil.copy2(input_path, output_path)

    def _get_duration(self, video_path: Path) -> float:
        """Get video duration in seconds."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "json",
            str(video_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except Exception:
            return 0.0

    @property
    def cost_total(self) -> float:
        """Total estimated API cost so far."""
        return self._cost_total
