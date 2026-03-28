"""
Full-song video generation pipeline: Lexicon track -> Resolume-ready video on NAS.

Orchestrates the entire flow:
1. Query Lexicon API for track metadata (BPM, genre, duration, energy, happiness)
2. Copy audio from NAS to local temp (via SSH cat)
3. Analyze audio (using Lexicon BPM, phrase segmentation, mood analysis)
4. Load brand guide from config/brands/<brand>.yaml
5. Plan segments based on song structure (intro/buildup/drop/breakdown/outro)
6. Generate keyframe images per segment using Flux LoRA (fal.ai) with brand prompts
7. Animate keyframes into video segments using Kling image-to-video (fal.ai)
8. Chain segments using last-frame extraction for visual continuity
9. Stitch all segments into one continuous video matching exact audio duration
10. Encode to DXV codec for Resolume (ffmpeg -c:v dxv -format dxt1)
11. Name output to match ID3 title tag (for Resolume auto-matching)
12. Push to NAS at /volume1/vj-content/<track_name>/
13. Save metadata for the "Will See" composition builder
"""
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx
import yaml

from .encoder import (
    encode_for_resolume,
    extract_frame,
    get_video_info,
    name_for_resolume,
    stitch_videos,
)
from .lexicon import (
    LexiconClient,
    NAS_VJ_CONTENT_PREFIX,
    LOCAL_VJ_MOUNT,
    copy_from_nas,
    lexicon_to_nas_path,
    lexicon_track_to_analysis_overrides,
    nas_file_exists,
    nas_ssh_cmd,
    push_to_nas,
    sanitize_track_dirname,
)

logger = logging.getLogger(__name__)

# Project root for config/brand files
_PROJECT_ROOT = Path(__file__).parent.parent


def _load_brand_config(brand_name: str) -> dict:
    """Load a brand YAML config from config/brands/<name>.yaml."""
    brand_file = _PROJECT_ROOT / "config" / "brands" / f"{brand_name}.yaml"
    if not brand_file.exists():
        raise FileNotFoundError(
            f"Brand config not found: {brand_file}\n"
            f"Available brands: {', '.join(p.stem for p in (_PROJECT_ROOT / 'config' / 'brands').glob('*.yaml'))}"
        )
    with open(brand_file) as f:
        return yaml.safe_load(f)


def _load_lora_url(brand_name: str) -> str:
    """Load LoRA weights URL from assets/<brand>_lora.json."""
    lora_file = _PROJECT_ROOT / "assets" / f"{brand_name}_lora.json"
    if not lora_file.exists():
        logger.warning(f"No LoRA file found at {lora_file}, proceeding without LoRA")
        return ""
    data = json.loads(lora_file.read_text())
    return data.get("diffusers_lora_file", {}).get("url", "")


class FullSongPipeline:
    """End-to-end pipeline: Lexicon track -> Resolume-ready video on NAS."""

    def __init__(self, brand_config: dict, fal_key: str, openai_key: str):
        self.brand = brand_config
        self.fal_key = fal_key
        self.openai_key = openai_key
        self.lora_url = brand_config.get("lora_weights_url", "")
        # Extract brand output specs
        output_spec = brand_config.get("output", {})
        res = output_spec.get("resolution", "1920x1080")
        parts = res.split("x")
        self.width = int(parts[0]) if len(parts) == 2 else 1920
        self.height = int(parts[1]) if len(parts) == 2 else 1080
        self.fps = output_spec.get("fps", 30)
        self.codec = output_spec.get("codec", "dxv")

    def generate_for_track(
        self,
        track: dict,
        output_dir: Path,
        style_override: str = "",
        quality: str = "high",
        dry_run: bool = False,
    ) -> dict:
        """Full pipeline for one track. Returns metadata dict.

        Args:
            track: Lexicon track dict with title, artist, bpm, location, etc.
            output_dir: Local working directory for intermediate files.
            style_override: Optional style keyword to layer on brand prompts.
            quality: Generation quality (draft/standard/high).
            dry_run: If True, plan and return segment info without generating.

        Returns:
            Metadata dict with title, artist, bpm, nas_path, local_vj_path, segments, etc.
        """
        title = track.get("title", "Unknown")
        artist = track.get("artist", "Unknown")
        bpm = track.get("bpm")
        location = track.get("location", "")
        track_dirname = sanitize_track_dirname(title)

        logger.info(f"Pipeline start: {artist} - {title} ({bpm} BPM)")

        # Check if already exists on NAS
        resolume_filename = name_for_resolume(title, extension=".mov")
        nas_output_dir = f"{NAS_VJ_CONTENT_PREFIX}{track_dirname}/"
        nas_final = f"{nas_output_dir}{resolume_filename}"

        if nas_file_exists(nas_final):
            logger.info(f"Already exists on NAS: {nas_final}")
            return {
                "title": title,
                "artist": artist,
                "bpm": bpm,
                "nas_path": nas_final,
                "local_vj_path": str(LOCAL_VJ_MOUNT / track_dirname / resolume_filename),
                "skipped": True,
            }

        # Step 1: Convert path and copy audio from NAS
        nas_audio_path = lexicon_to_nas_path(location)
        audio_ext = Path(location).suffix or ".flac"
        local_audio = output_dir / track_dirname / f"audio{audio_ext}"
        local_audio.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Step 1: Copying audio from NAS: {nas_audio_path}")
        copy_from_nas(nas_audio_path, local_audio)

        # Step 2: Analyze audio with Lexicon overrides
        logger.info("Step 2: Analyzing audio...")
        overrides = lexicon_track_to_analysis_overrides(track)
        analysis = self._analyze_audio(local_audio, overrides)

        # Step 3: Plan segments based on song structure + brand guide
        logger.info("Step 3: Planning segments...")
        segments = self._plan_segments(analysis, style_override)

        if dry_run:
            return {
                "title": title,
                "artist": artist,
                "bpm": overrides.get("bpm", bpm),
                "genre": overrides.get("genre", ""),
                "duration": analysis.get("duration", 0),
                "segments": segments,
                "dry_run": True,
            }

        # Step 4-7: Generate keyframes and animate segments
        logger.info(f"Steps 4-7: Generating {len(segments)} video segments...")
        work_dir = output_dir / track_dirname / "segments"
        work_dir.mkdir(parents=True, exist_ok=True)

        segment_videos = []
        prev_frame_path = None

        for i, seg in enumerate(segments):
            logger.info(
                f"  Segment {i+1}/{len(segments)}: {seg['label']} "
                f"({seg['start']:.1f}s - {seg['end']:.1f}s, {seg['duration']:.1f}s)"
            )

            # Generate keyframe (use previous segment's last frame for continuity)
            keyframe_path = work_dir / f"keyframe_{i:03d}.png"
            if prev_frame_path and prev_frame_path.exists():
                # Use last frame from previous segment as starting point
                keyframe_path = prev_frame_path
                logger.info(f"    Using last frame from previous segment for continuity")
            else:
                keyframe_path = self._generate_keyframe(
                    prompt=seg["prompt"],
                    lora_url=self.lora_url,
                    output_path=keyframe_path,
                    quality=quality,
                )

            # Animate keyframe into video segment
            segment_video = work_dir / f"segment_{i:03d}.mp4"
            segment_video = self._animate_segment(
                keyframe=keyframe_path,
                prompt=seg["motion_prompt"],
                duration=seg["duration"],
                output_path=segment_video,
            )
            segment_videos.append(segment_video)

            # Extract last frame for next segment's continuity chain
            try:
                prev_frame_path = work_dir / f"lastframe_{i:03d}.png"
                video_info = get_video_info(segment_video)
                last_time = max(0, video_info["duration"] - 0.05)
                extract_frame(segment_video, last_time, prev_frame_path)
            except Exception as e:
                logger.warning(f"    Last-frame extraction failed: {e}")
                prev_frame_path = None

        # Step 8: Stitch all segments into one continuous video
        logger.info("Step 8: Stitching segments...")
        target_duration = analysis.get("duration", 0)
        raw_video = output_dir / track_dirname / f"{title}.mp4"
        stitch_videos(
            segments=segment_videos,
            output_path=raw_video,
            target_duration=target_duration,
            crossfade_seconds=0.5,
            fps=self.fps,
        )

        # Step 9: Encode to DXV for Resolume
        logger.info("Step 9: Encoding to DXV...")
        final_video = output_dir / track_dirname / resolume_filename
        encode_for_resolume(
            input_path=raw_video,
            output_path=final_video,
            codec=self.codec,
            fps=self.fps,
            width=self.width,
            height=self.height,
        )

        # Step 10: Push to NAS
        logger.info(f"Step 10: Pushing to NAS: {nas_final}")
        push_to_nas(final_video, nas_final)

        # Step 11: Save metadata
        metadata = {
            "title": title,
            "artist": artist,
            "bpm": overrides.get("bpm", bpm),
            "key": overrides.get("key", ""),
            "genre": overrides.get("genre", ""),
            "energy": overrides.get("energy"),
            "happiness": overrides.get("happiness"),
            "duration": target_duration,
            "nas_path": nas_final,
            "local_vj_path": str(LOCAL_VJ_MOUNT / track_dirname / resolume_filename),
            "segments": len(segments),
            "brand": self.brand.get("name", ""),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        meta_path = output_dir / track_dirname / "track_metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2))

        logger.info(f"Pipeline complete: {title} -> {nas_final}")
        return metadata

    def _analyze_audio(self, audio_path: Path, overrides: dict) -> dict:
        """Analyze audio file with Lexicon metadata overrides.

        Returns analysis dict with phrases, mood, duration, etc.
        """
        from .analyzer.audio import analyze_track

        analysis = analyze_track(
            str(audio_path),
            bpm_override=overrides.get("bpm"),
        )
        analysis.key = overrides.get("key", "")
        analysis.genre_hint = overrides.get("genre", "")
        analysis_dict = analysis.to_dict()

        # Mood analysis
        try:
            from .analyzer.mood import analyze_mood
            mood = analyze_mood(str(audio_path))
            analysis.mood = mood.to_dict()
            analysis_dict["mood"] = mood.to_dict()
            logger.info(f"  Mood: {mood.dominant_mood} ({mood.quadrant})")
        except Exception as e:
            logger.debug(f"  Mood analysis skipped: {e}")

        return analysis_dict

    def _plan_segments(
        self,
        analysis: dict,
        style_override: str = "",
    ) -> list[dict]:
        """Plan video segments based on song structure + brand guide.

        Each segment gets: start_time, end_time, duration, section_label,
        prompt (for keyframe generation), motion_prompt (for animation).
        """
        phrases = analysis.get("phrases", [])
        mood = analysis.get("mood", {})
        mood_quadrant = mood.get("quadrant", "euphoric")
        mood_descriptor = mood.get("mood_descriptor", "")
        genre = analysis.get("genre_hint", "")

        brand_sections = self.brand.get("sections", {})
        brand_style_base = self.brand.get("style", {}).get("base", "")
        mood_modifiers = self.brand.get("mood_modifiers", {})
        genre_modifiers = self.brand.get("genre_modifiers", {})

        # Get mood modifier for this track
        mood_mod = mood_modifiers.get(mood_quadrant, {})
        mood_colors = mood_mod.get("colors", "")
        mood_atmosphere = mood_mod.get("atmosphere", "")
        mood_psychedelic = mood_mod.get("psychedelic", "")

        # Get genre modifier
        genre_lower = genre.lower()
        genre_mod = genre_modifiers.get(genre_lower, {})
        genre_extra = genre_mod.get("extra", "")
        genre_pixel = genre_mod.get("pixel_style", "")

        segments = []

        if not phrases:
            # Fallback: single segment covering entire track
            duration = analysis.get("duration", 60.0)
            section = brand_sections.get("drop", {})
            prompt = self._build_prompt(
                section.get("prompt", brand_style_base),
                mood_colors, mood_atmosphere, genre_extra, genre_pixel,
                style_override,
            )
            segments.append({
                "start": 0.0,
                "end": duration,
                "duration": duration,
                "label": "drop",
                "energy": 0.5,
                "prompt": prompt,
                "motion_prompt": section.get("motion", "dynamic motion"),
            })
            return segments

        for i, phrase in enumerate(phrases):
            p_start = phrase["start"]
            p_end = phrase["end"]
            p_duration = p_end - p_start
            p_label = phrase.get("label", "buildup")
            p_energy = phrase.get("energy", 0.5)

            if p_duration <= 0:
                continue

            # Map phrase label to brand section
            section_key = self._map_label_to_section(p_label)
            section = brand_sections.get(section_key, brand_sections.get("drop", {}))

            # Build prompts using brand guide
            section_prompt = section.get("prompt", brand_style_base)
            prompt = self._build_prompt(
                section_prompt,
                mood_colors, mood_atmosphere, genre_extra, genre_pixel,
                style_override,
            )
            motion = section.get("motion", "smooth continuous motion")
            energy_label = section.get("energy", "moderate")

            segments.append({
                "start": p_start,
                "end": p_end,
                "duration": p_duration,
                "label": section_key,
                "energy": p_energy,
                "prompt": prompt,
                "motion_prompt": f"{motion}, {mood_psychedelic}" if mood_psychedelic else motion,
                "energy_label": energy_label,
                "segment_index": i,
            })

        return segments

    def _map_label_to_section(self, label: str) -> str:
        """Map analysis phrase labels to brand section keys."""
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

    def _build_prompt(
        self,
        section_prompt: str,
        mood_colors: str,
        mood_atmosphere: str,
        genre_extra: str,
        genre_pixel: str,
        style_override: str,
    ) -> str:
        """Combine section prompt with mood/genre/style modifiers."""
        parts = [section_prompt]
        if mood_colors:
            parts.append(mood_colors)
        if mood_atmosphere:
            parts.append(mood_atmosphere)
        if genre_extra:
            parts.append(genre_extra)
        if genre_pixel:
            parts.append(genre_pixel)
        if style_override:
            parts.append(style_override)
        return ", ".join(p for p in parts if p)

    def _generate_keyframe(
        self,
        prompt: str,
        lora_url: str,
        output_path: Path,
        quality: str = "high",
    ) -> Path:
        """Generate keyframe image via Flux LoRA on fal.ai.

        Uses fal-ai/flux-lora with the brand's trained LoRA weights
        for consistent visual identity.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.fal_key:
            raise ValueError("FAL_KEY required for keyframe generation")

        # Set fal key for fal_client
        os.environ["FAL_KEY"] = self.fal_key

        try:
            import fal_client
        except ImportError:
            raise ImportError(
                "fal-client required for Flux LoRA. Install: pip install fal-client"
            )

        # Flux LoRA model on fal.ai
        model_id = "fal-ai/flux-lora"

        arguments = {
            "prompt": prompt,
            "image_size": {
                "width": self.width,
                "height": self.height,
            },
            "num_images": 1,
            "output_format": "png",
            "guidance_scale": 3.5,
            "num_inference_steps": 28,
            "enable_safety_checker": False,
        }

        # Add LoRA weights if available
        if lora_url:
            arguments["loras"] = [
                {
                    "path": lora_url,
                    "scale": 1.0,
                }
            ]

        logger.info(f"Generating keyframe via Flux LoRA: {prompt[:80]}...")

        handle = fal_client.submit(model_id, arguments=arguments)
        result = handle.get()

        # Extract image URL
        image_url = None
        if isinstance(result, dict):
            images = result.get("images", [])
            if images and isinstance(images[0], dict):
                image_url = images[0].get("url")

        if not image_url:
            raise RuntimeError(f"No image URL in fal.ai Flux response: {result}")

        # Download the image
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            img_resp = client.get(image_url)
            img_resp.raise_for_status()
            output_path.write_bytes(img_resp.content)

        logger.info(
            f"Keyframe saved: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)"
        )
        return output_path

    def _animate_segment(
        self,
        keyframe: Path,
        prompt: str,
        duration: float,
        output_path: Path,
    ) -> Path:
        """Animate keyframe via Kling image-to-video on fal.ai.

        Uses kling-v1-5 pro for high quality animation. Segments longer
        than the model's max duration (10s) are split into chunks and
        chained via last-frame extraction.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.fal_key:
            raise ValueError("FAL_KEY required for video generation")

        os.environ["FAL_KEY"] = self.fal_key

        try:
            import fal_client
        except ImportError:
            raise ImportError(
                "fal-client required for Kling. Install: pip install fal-client"
            )

        model_id = "fal-ai/kling-video/v1.5/pro/image-to-video"
        max_model_duration = 10.0  # Kling max per generation

        if duration <= max_model_duration:
            # Single generation
            return self._fal_image_to_video(
                fal_client, model_id, keyframe, prompt, duration, output_path
            )

        # Long segment: chain multiple generations
        logger.info(
            f"    Long segment ({duration:.1f}s), chaining "
            f"{int(duration / max_model_duration) + 1} sub-segments"
        )
        sub_videos = []
        remaining = duration
        current_keyframe = keyframe
        sub_idx = 0

        while remaining > 0:
            chunk_dur = min(remaining, max_model_duration)
            if chunk_dur < 2.0 and sub_videos:
                # Too short for a meaningful generation, skip
                break

            sub_path = output_path.parent / f"{output_path.stem}_sub{sub_idx:02d}.mp4"
            sub_video = self._fal_image_to_video(
                fal_client, model_id, current_keyframe, prompt, chunk_dur, sub_path
            )
            sub_videos.append(sub_video)

            # Extract last frame for next chunk
            try:
                next_kf = output_path.parent / f"chain_kf_{sub_idx:02d}.png"
                info = get_video_info(sub_video)
                extract_frame(sub_video, max(0, info["duration"] - 0.05), next_kf)
                current_keyframe = next_kf
            except Exception as e:
                logger.warning(f"    Chain frame extraction failed: {e}")

            remaining -= chunk_dur
            sub_idx += 1

        if len(sub_videos) == 1:
            # Only one sub-video, just rename
            sub_videos[0].rename(output_path)
            return output_path

        # Stitch sub-videos
        stitch_videos(
            segments=sub_videos,
            output_path=output_path,
            target_duration=duration,
            crossfade_seconds=0.3,
            fps=self.fps,
        )
        return output_path

    def _fal_image_to_video(
        self,
        fal_client,
        model_id: str,
        keyframe_path: Path,
        prompt: str,
        duration: float,
        output_path: Path,
    ) -> Path:
        """Submit one image-to-video generation via fal.ai."""
        # Upload keyframe
        image_url = fal_client.upload_file(str(keyframe_path))

        arguments = {
            "prompt": prompt,
            "image_url": image_url,
            "duration": str(min(duration, 10.0)),
        }

        logger.info(f"    fal.ai Kling i2v: {duration:.1f}s, prompt={prompt[:60]}...")

        handle = fal_client.submit(model_id, arguments=arguments)
        result = handle.get()

        # Extract video URL
        video_url = None
        if isinstance(result, dict):
            video = result.get("video", {})
            if isinstance(video, dict):
                video_url = video.get("url")
            elif isinstance(video, str):
                video_url = video
            if not video_url:
                output = result.get("output", {})
                if isinstance(output, dict):
                    video_url = output.get("url") or output.get("video_url")

        if not video_url:
            raise RuntimeError(f"No video URL in fal.ai Kling response: {result}")

        # Download video
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            resp = client.get(video_url)
            resp.raise_for_status()
            output_path.write_bytes(resp.content)

        logger.info(f"    Segment saved: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
        return output_path

    def _stitch_and_encode(
        self,
        segments: list[Path],
        target_duration: float,
        output: Path,
    ) -> Path:
        """Stitch segments, trim to exact duration, encode DXV.

        This is a convenience method wrapping stitch_videos + encode_for_resolume.
        """
        # Stitch to intermediate mp4
        intermediate = output.parent / f"{output.stem}_stitched.mp4"
        stitch_videos(
            segments=segments,
            output_path=intermediate,
            target_duration=target_duration,
            crossfade_seconds=0.5,
            fps=self.fps,
        )

        # Encode to Resolume format
        encode_for_resolume(
            input_path=intermediate,
            output_path=output,
            codec=self.codec,
            fps=self.fps,
            width=self.width,
            height=self.height,
        )

        return output

    def _push_to_nas(self, local_path: Path, remote_dir: str) -> str:
        """Push file to NAS via SSH cat.

        Args:
            local_path: Local file to push.
            remote_dir: Remote directory on NAS (will be created if needed).

        Returns:
            Full remote path of the pushed file.
        """
        remote_path = f"{remote_dir}{local_path.name}"
        push_to_nas(local_path, remote_path)
        return remote_path
