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
12. Push to NAS at /volume1/vj-content/My Show/Songs/<track_name>/
13. Save metadata for the composition builder
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

from .analyzer.anticipation import apply_anticipation
from .analyzer.genre_vocabulary import (
    genre_to_prompt_fragment,
    merge_genre_with_brand,
)
from .analyzer.lyrics import get_content_prompt_modifier, get_lyrics
from .analyzer.sonic_mapper import (
    analyze_segment_sonics,
    create_segment_sonic_profiles,
    enhance_segment_prompt,
)

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
from .nas import NASManager

logger = logging.getLogger(__name__)

# Project root for config/brand files
_PROJECT_ROOT = Path(__file__).parent.parent

# Common suffixes stripped from track titles to derive NAS folder names.
# "Mind Control (Original Mix)" -> "Mind Control"
import re as _re
_TITLE_SUFFIX_RE = _re.compile(
    r"\s*\("
    r"(?:Original Mix|Extended Mix|Extended Edit|Extended Remix|"
    r"Radio Edit|Club Mix|Remix|VIP|Dub Mix|Instrumental Mix)"
    r"(?:\s*-\s*[^)]+)?"   # optional sub-part, e.g. "(Hamdi Extended Remix)"
    r"\)\s*$",
    _re.IGNORECASE,
)


def _derive_folder_name(title: str) -> str:
    """Derive a simplified NAS folder name from a track title.

    Strips common mix-type suffixes so folder names stay clean:
        "Mind Control (Original Mix)"  -> "Mind Control"
        "Summertime Blues (Extended Mix)" -> "Summertime Blues"
        "Afterglow (Extended Mix)"     -> "Afterglow"
    """
    name = _TITLE_SUFFIX_RE.sub("", title).strip()
    return name if name else title


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
    """End-to-end pipeline: Lexicon track -> Resolume-ready video on NAS.

    Supports two generation modes:
    - v1 (linear): Generate unique video segment per phrase chunk (default, legacy)
    - v2 (loop-bank): Generate 5-10 short loops, one per phrase type,
      loop within phrase duration, add beat-sync effects, stitch with crossfade.
      Set generation_mode="v2" to enable.
    """

    def __init__(
        self,
        brand_config: dict,
        fal_key: str,
        openai_key: str,
        nas_manager: Optional[NASManager] = None,
        cost_guard=None,
        generation_mode: str = "v1",
    ):
        self.brand = brand_config
        self.fal_key = fal_key
        self.openai_key = openai_key
        self.lora_url = brand_config.get("lora_weights_url", "")
        self.nas = nas_manager or NASManager()
        self.cost_guard = cost_guard
        self._cost_state = None
        self.generation_mode = generation_mode  # "v1" or "v2"
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
        # NAS folder uses simplified name (no mix-type suffix)
        nas_folder = track.get("folder_name") or _derive_folder_name(title)

        logger.info(f"Pipeline start: {artist} - {title} ({bpm} BPM)")

        # Check if already exists on NAS
        # NAS video path: <base>/<nas_folder>/<title>.mov
        resolume_filename = name_for_resolume(title, extension=".mov")
        nas_track_dir = f"{self.nas.base_path}/{nas_folder}"
        nas_final = f"{nas_track_dir}/{title}.mov"
        resolume_path = f"{self.nas.resolume_mount}/{nas_folder}/{title}.mov"

        if self.nas.track_has_video(nas_folder, title=title):
            logger.info(f"Already exists on NAS: {nas_final}")
            return {
                "title": title,
                "artist": artist,
                "bpm": bpm,
                "nas_path": nas_final,
                "local_vj_path": resolume_path,
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

        # Step 2b: Content analysis (title + lyrics)
        logger.info("Step 2b: Analyzing song content (title/lyrics)...")
        content_modifier = ""
        try:
            lyrics = get_lyrics(
                title, artist,
                audio_path=str(local_audio),
                openai_key=self.openai_key,
            )
            content_modifier = get_content_prompt_modifier(
                title, artist, lyrics,
                openai_key=self.openai_key,
            )
            if content_modifier:
                logger.info(f"  Content modifier: {content_modifier[:100]}...")
        except Exception as e:
            logger.warning(f"  Content analysis skipped: {e}")

        # Step 3: Plan segments based on song structure + brand guide
        logger.info("Step 3: Planning segments...")
        segments = self._plan_segments(analysis, style_override,
                                       content_modifier=content_modifier)

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

        # ── V2 Loop-Bank mode ──────────────────────────────────────────
        if self.generation_mode == "v2":
            return self._generate_v2_loopbank(
                track, analysis, overrides, output_dir, track_dirname,
                title, artist, bpm, quality, style_override, content_modifier,
                nas_folder, nas_final, resolume_path, resolume_filename,
            )

        # ── V1 Linear mode (legacy) ──────────────────────────────────
        # Step 4-7: Generate keyframes and animate segments
        logger.info(f"Steps 4-7: Generating {len(segments)} video segments...")
        work_dir = output_dir / track_dirname / "segments"
        work_dir.mkdir(parents=True, exist_ok=True)

        # Cost guard: estimate and enforce budget
        video_model = self.brand.get("video_model", "kling-v1")
        if self.cost_guard:
            target_duration = analysis.get("duration", 0)
            estimate = self.cost_guard.estimate_cost(
                model=video_model,
                duration=target_duration,
                segment_length=10.0,
            )
            logger.info(
                f"  Cost estimate: ${estimate.total_estimated:.2f} "
                f"({estimate.total_segments} segments, model={estimate.model})"
            )
            if estimate.warning:
                logger.warning(f"  Cost warning: {estimate.warning}")
            if estimate.suggested_model:
                video_model = estimate.suggested_model
                logger.info(f"  Auto-downgraded to {video_model} to stay within budget")

            self._cost_state = self.cost_guard.start_song(
                track_title=title,
                track_id=track.get("id", ""),
                model=video_model,
                total_segments=len(segments),
            )

        segment_videos = []
        prev_frame_path = None

        for i, seg in enumerate(segments):
            logger.info(
                f"  Segment {i+1}/{len(segments)}: {seg['label']} "
                f"({seg['start']:.1f}s - {seg['end']:.1f}s, {seg['duration']:.1f}s)"
            )

            # Cost guard: check budget before generating
            if self.cost_guard and self._cost_state:
                from .cost_guard import MODEL_COSTS
                model_info = MODEL_COSTS.get(
                    self._cost_state.model,
                    {"cost_per_gen": 0.50},
                )
                est_cost = model_info["cost_per_gen"] + 0.03  # video + keyframe
                result = self.cost_guard.check_budget(self._cost_state, est_cost)
                if result == "stop":
                    logger.warning(
                        f"  Cost cap reached after segment {i}/{len(segments)}. "
                        f"Saving {len(segment_videos)} segments generated so far."
                    )
                    break
                elif result == "downgrade":
                    logger.warning(
                        f"  Budget downgrade: now using {self._cost_state.model}"
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
                # Log keyframe cost
                if self.cost_guard and self._cost_state:
                    self.cost_guard.log_call(
                        self._cost_state,
                        model="fal-ai/flux-lora",
                        cost=0.03,
                        segment_index=i,
                        call_type="keyframe",
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

            # Log video generation cost
            if self.cost_guard and self._cost_state:
                from .cost_guard import MODEL_COSTS
                model_info = MODEL_COSTS.get(
                    self._cost_state.model,
                    {"cost_per_gen": 0.50},
                )
                self.cost_guard.log_call(
                    self._cost_state,
                    model=self._cost_state.model,
                    cost=model_info["cost_per_gen"],
                    segment_index=i,
                    call_type="video",
                )
                self._cost_state.segments_completed = i + 1

            # Extract last frame for next segment's continuity chain
            try:
                prev_frame_path = work_dir / f"lastframe_{i:03d}.png"
                video_info = get_video_info(segment_video)
                last_time = max(0, video_info["duration"] - 0.05)
                extract_frame(segment_video, last_time, prev_frame_path)
            except Exception as e:
                logger.warning(f"    Last-frame extraction failed: {e}")
                prev_frame_path = None

        # If cost guard stopped generation early with no segments, raise error
        if not segment_videos:
            raise RuntimeError(
                f"No segments generated — cost cap ${self.cost_guard.max_cost:.2f} "
                f"prevents even one segment for this model"
            )

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

        # Step 10: Push to NAS via NASManager
        # Folder = simplified name (e.g. "Mind Control"), file = full title
        logger.info(f"Step 10: Pushing to NAS: {nas_final}")
        self.nas.push_video(
            final_video, nas_folder, codec="mov", filename=title,
        )

        # Step 11: Save metadata (locally and on NAS)
        # Include cost tracking data in metadata
        cost_data = {}
        if self.cost_guard and self._cost_state:
            cost_data = self.cost_guard.summary(self._cost_state)

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
            "local_vj_path": resolume_path,
            "segments": len(segment_videos),
            "segments_planned": len(segments),
            "brand": self.brand.get("name", ""),
            "model": cost_data.get("model_used", ""),
            "cost": cost_data.get("cost_so_far", 0.0),
            "cost_guard": cost_data,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        # Save locally
        meta_path = output_dir / track_dirname / "track_metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2))
        # Push metadata to NAS and register in .rsv
        self.nas.push_metadata(metadata, nas_folder)
        self.nas.register_track(nas_folder, metadata)

        # Step 12: Auto-rebuild the show composition with all tracks
        logger.info("Step 12: Auto-rebuilding show composition...")
        try:
            from .resolume.show import auto_rebuild_show
            show_path = auto_rebuild_show(self.nas, show_name="My Show")
            logger.info(f"Show rebuilt: {show_path}")
        except Exception as e:
            logger.warning(f"Auto-rebuild show failed (non-fatal): {e}")

        logger.info(f"Pipeline complete: {title} -> {nas_final}")
        return metadata

    def _analyze_audio(self, audio_path: Path, overrides: dict) -> dict:
        """Analyze audio file with Lexicon metadata overrides.

        Returns analysis dict with phrases, mood, duration, sonic event timeline, etc.
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

        # Stem separation + sonic event timeline
        try:
            from .analyzer.stems import create_event_timeline
            logger.info("  Running stem separation and event detection...")
            timeline = create_event_timeline(
                str(audio_path), fps=self.fps,
            )
            analysis_dict["sonic_timeline"] = timeline
            logger.info(
                f"  Sonic timeline: {timeline['summary']['total_events']} events "
                f"across {len(timeline['stems'])} stems"
            )
        except Exception as e:
            logger.warning(f"  Stem analysis skipped: {e}")

        return analysis_dict

    def _plan_segments(
        self,
        analysis: dict,
        style_override: str = "",
        content_modifier: str = "",
    ) -> list[dict]:
        """Plan video segments based on song structure + brand guide.

        Each segment gets: start_time, end_time, duration, section_label,
        prompt (for keyframe generation), motion_prompt (for animation).

        When a sonic_timeline is available in the analysis, sonic profiles
        are created for each segment and their prompts are enhanced with
        music-reactive descriptions.
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

        # Get genre modifier (brand-level)
        genre_lower = genre.lower()
        genre_mod = genre_modifiers.get(genre_lower, {})
        genre_extra = genre_mod.get("extra", "")
        genre_pixel = genre_mod.get("pixel_style", "")

        # Get structured genre vocabulary fragment (from config/genres/*.yaml)
        genre_vocab_fragment = genre_to_prompt_fragment(
            genre, section="drop", brand_config=self.brand,
        ) if genre else ""

        segments = []

        if not phrases:
            # Fallback: single segment covering entire track
            duration = analysis.get("duration", 60.0)
            section = brand_sections.get("drop", {})
            prompt = self._build_prompt(
                section.get("prompt", brand_style_base),
                mood_colors, mood_atmosphere, genre_extra, genre_pixel,
                style_override, content_modifier, genre_vocab_fragment,
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
        else:
            bpm = analysis.get("bpm", 128.0)
            beat_duration = 60.0 / bpm
            max_segment_duration = 10.0  # Match video model max

            for phrase in phrases:
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

                # Build prompts using brand guide + genre vocabulary
                section_prompt = section.get("prompt", brand_style_base)
                seg_genre_fragment = genre_to_prompt_fragment(
                    genre, section=section_key, brand_config=self.brand,
                ) if genre else genre_vocab_fragment
                prompt = self._build_prompt(
                    section_prompt,
                    mood_colors, mood_atmosphere, genre_extra, genre_pixel,
                    style_override, content_modifier, seg_genre_fragment,
                )
                motion = section.get("motion", "smooth continuous motion")
                energy_label = section.get("energy", "moderate")

                if p_duration <= max_segment_duration:
                    # Phrase fits in one segment — exact phrase boundaries
                    segments.append({
                        "start": p_start,
                        "end": p_end,
                        "duration": p_duration,
                        "label": section_key,
                        "energy": p_energy,
                        "prompt": prompt,
                        "motion_prompt": f"{motion}, {mood_psychedelic}" if mood_psychedelic else motion,
                        "energy_label": energy_label,
                        "segment_index": len(segments),
                        "sub_index": 0,
                    })
                else:
                    # Split long phrase into segments of max_segment_duration.
                    # Each segment = exactly ONE API call. No sub-chunking.
                    sub_idx = 0
                    current = p_start

                    while current < p_end - 1.0:
                        seg_end = min(current + max_segment_duration, p_end)
                        # Snap to nearest beat for clean transitions
                        beats_in = (seg_end - p_start) / beat_duration
                        seg_end = p_start + round(beats_in) * beat_duration
                        seg_end = min(seg_end, p_end)
                        if seg_end <= current:
                            seg_end = min(current + max_segment_duration, p_end)

                        segments.append({
                            "start": current,
                            "end": seg_end,
                            "duration": seg_end - current,
                            "label": section_key,
                            "energy": p_energy,
                            "prompt": prompt,
                            "motion_prompt": f"{motion}, {mood_psychedelic}" if mood_psychedelic else motion,
                            "energy_label": energy_label,
                            "segment_index": len(segments),
                            "sub_index": sub_idx,
                        })
                        sub_idx += 1
                        current = seg_end

                    # Absorb tiny remainder into last segment
                    if current < p_end and segments:
                        remainder = p_end - current
                        if remainder < 1.0:
                            segments[-1]["end"] = p_end
                            segments[-1]["duration"] = p_end - segments[-1]["start"]
                        else:
                            segments.append({
                                "start": current,
                                "end": p_end,
                                "duration": remainder,
                                "label": section_key,
                                "energy": p_energy,
                                "prompt": prompt,
                                "motion_prompt": f"{motion}, {mood_psychedelic}" if mood_psychedelic else motion,
                                "energy_label": energy_label,
                                "segment_index": len(segments),
                                "sub_index": sub_idx,
                            })

        # Enhance segment prompts with sonic data when available
        sonic_timeline = analysis.get("sonic_timeline")
        if sonic_timeline and segments:
            try:
                sonic_profiles = create_segment_sonic_profiles(
                    sonic_timeline, segments, brand_config=self.brand,
                )
                for seg, profile in zip(segments, sonic_profiles):
                    seg["prompt"] = enhance_segment_prompt(
                        seg["prompt"], profile, include_eyes=True,
                    )
                    seg["sonic_profile"] = {
                        "dominant_stem": profile.dominant_stem,
                        "drums_energy": profile.drums_energy,
                        "bass_energy": profile.bass_energy,
                        "synth_energy": profile.synth_energy,
                        "vocals_energy": profile.vocals_energy,
                        "event_count": profile.event_count,
                        "has_bass_drop": profile.has_bass_drop,
                        "has_synth_stab": profile.has_synth_stab,
                        "has_vocal": profile.has_vocal,
                        "synth_character": profile.synth_character,
                    }
                logger.info(
                    f"  Enhanced {len(sonic_profiles)} segment prompts with sonic data"
                )
            except Exception as e:
                logger.warning(f"  Sonic prompt enhancement failed: {e}")

        # Apply drop anticipation to buildup segments
        bpm = analysis.get("bpm", 128.0)
        try:
            segments = apply_anticipation(segments, bpm, brand_config=self.brand)
            antic_count = sum(1 for s in segments if "anticipation" in s)
            if antic_count:
                logger.info(f"  Applied anticipation to {antic_count} segments")
        except Exception as e:
            logger.warning(f"  Anticipation analysis failed: {e}")

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
        content_modifier: str = "",
        genre_vocab_fragment: str = "",
    ) -> str:
        """Combine section prompt with mood/genre/style/content modifiers."""
        parts = [section_prompt]
        if content_modifier:
            parts.append(content_modifier)
        if mood_colors:
            parts.append(mood_colors)
        if mood_atmosphere:
            parts.append(mood_atmosphere)
        if genre_extra:
            parts.append(genre_extra)
        if genre_pixel:
            parts.append(genre_pixel)
        if genre_vocab_fragment:
            parts.append(genre_vocab_fragment)
        if style_override:
            parts.append(style_override)
        return ", ".join(p for p in parts if p)

    def _generate_v2_loopbank(
        self,
        track: dict,
        analysis: dict,
        overrides: dict,
        output_dir: Path,
        track_dirname: str,
        title: str,
        artist: str,
        bpm: float,
        quality: str,
        style_override: str,
        content_modifier: str,
        nas_folder: str,
        nas_final: str,
        resolume_path: str,
        resolume_filename: str,
    ) -> dict:
        """V2 loop-bank generation: fewer API calls, rhythmic looping, beat-sync effects.

        Instead of 24+ unique segments, generates 5-10 loops (one per phrase type),
        loops each to fill its phrase duration, adds beat-synced effects, and stitches
        into one continuous video.
        """
        from .generator.loop_generator import LoopBankGenerator, LoopBankConfig

        logger.info(f"V2 LOOP-BANK MODE: generating loops for {title}")

        work_dir = output_dir / track_dirname / "loopbank"
        work_dir.mkdir(parents=True, exist_ok=True)

        video_model = self.brand.get("video_model", "kling-v1-5-pro")

        config = LoopBankConfig(
            width=self.width,
            height=self.height,
            fps=self.fps,
            video_model=video_model,
            fal_key=self.fal_key,
            openai_key=self.openai_key,
            lora_url=self.lora_url,
            work_dir=str(work_dir),
            quality=quality,
        )

        generator = LoopBankGenerator(config)
        raw_video = generator.generate(
            analysis=analysis,
            brand_config=self.brand,
            style_override=style_override,
            content_modifier=content_modifier,
        )

        # Encode to DXV for Resolume
        logger.info("Encoding to DXV...")
        final_video = output_dir / track_dirname / resolume_filename
        encode_for_resolume(
            input_path=raw_video,
            output_path=final_video,
            codec=self.codec,
            fps=self.fps,
            width=self.width,
            height=self.height,
        )

        # Push to NAS
        logger.info(f"Pushing to NAS: {nas_final}")
        self.nas.push_video(
            final_video, nas_folder, codec="mov", filename=title,
        )

        target_duration = analysis.get("duration", 0)
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
            "local_vj_path": resolume_path,
            "generation_mode": "v2-loopbank",
            "loops_generated": len(set(
                p.get("label", "drop")
                for p in analysis.get("phrases", [])
            )),
            "cost": generator.cost_total,
            "brand": self.brand.get("name", ""),
            "model": video_model,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        # Save locally
        meta_path = output_dir / track_dirname / "track_metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2))
        self.nas.push_metadata(metadata, nas_folder)
        self.nas.register_track(nas_folder, metadata)

        # Auto-rebuild show
        try:
            from .resolume.show import auto_rebuild_show
            show_path = auto_rebuild_show(self.nas, show_name="My Show")
            logger.info(f"Show rebuilt: {show_path}")
        except Exception as e:
            logger.warning(f"Auto-rebuild show failed (non-fatal): {e}")

        logger.info(
            f"V2 pipeline complete: {title} -> {nas_final} "
            f"(cost: ${generator.cost_total:.2f})"
        )
        return metadata

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

        # Skip regeneration if keyframe already exists (resume support).
        # Each Flux LoRA call costs ~$0.04 — avoiding duplicates adds up fast.
        if output_path.exists() and output_path.stat().st_size > 1000:
            logger.info(f"Keyframe already exists, skipping: {output_path.name}")
            return output_path

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

        Uses kling-v1-5 pro for high quality animation.
        Each segment = exactly ONE API call. Duration is clamped to the
        model's max (10s for Kling). Segments should already be planned
        to fit within the model's max duration — no sub-chunking.
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

        # Clamp to model max — no sub-chunking. One segment = one API call.
        if duration > max_model_duration:
            logger.warning(
                f"    Segment duration {duration:.1f}s exceeds model max "
                f"{max_model_duration}s. Clamping to {max_model_duration}s."
            )
            duration = max_model_duration

        return self._fal_image_to_video(
            fal_client, model_id, keyframe, prompt, duration, output_path
        )

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
        # Skip regeneration if output already exists (resume support).
        # Each Kling call costs $0.75, Veo 2 costs $4.00.
        if output_path.exists() and output_path.stat().st_size > 10000:
            logger.info(f"    Video segment already exists, skipping: {output_path.name}")
            return output_path

        # Upload keyframe
        image_url = fal_client.upload_file(str(keyframe_path))

        # Format duration per model requirements
        clamped = min(duration, 10.0)
        if "veo" in model_id.lower():
            # Veo 2/3 expects duration as '5s', '6s', '7s', or '8s'
            formatted_duration = f"{max(5, min(int(clamped), 8))}s"
        elif "kling" in model_id.lower():
            # Kling expects duration as exactly '5' or '10'
            formatted_duration = "5" if clamped <= 7 else "10"
        else:
            formatted_duration = str(int(clamped))

        arguments = {
            "prompt": prompt,
            "image_url": image_url,
            "duration": formatted_duration,
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
        """Push file to NAS via NASManager.

        Args:
            local_path: Local file to push.
            remote_dir: Remote directory on NAS (will be created if needed).

        Returns:
            Full remote path of the pushed file.
        """
        remote_path = f"{remote_dir}{local_path.name}"
        self.nas._push_file(local_path, remote_path)
        return remote_path
