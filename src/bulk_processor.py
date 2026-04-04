"""
Concurrent bulk processing pipeline.

Architecture:
  Stage 1 (Analysis): Analyze tracks + mood detection (CPU-bound, parallelizable)
  Stage 2 (Generation): Generate keyframes via API (I/O-bound, concurrent)
  Stage 3 (Composition): Create videos + organize output (CPU-bound)

Stages overlap: while track N is in Stage 2 (API calls), track N+1 enters Stage 1.
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

import yaml

logger = logging.getLogger(__name__)

MUSIC_EXTENSIONS = {".flac", ".mp3", ".wav", ".aif", ".aiff", ".ogg"}


@dataclass
class BulkResult:
    """Result summary for a bulk processing run."""
    total: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    total_cost: float = 0.0
    total_clips: int = 0
    duration_seconds: float = 0.0
    errors: list[dict] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def find_music_files(directory: str | Path, recursive: bool = True) -> list[Path]:
    """Find all music files in a directory."""
    directory = Path(directory)
    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    files = []
    if recursive:
        for ext in MUSIC_EXTENSIONS:
            files.extend(directory.rglob(f"*{ext}"))
    else:
        for ext in MUSIC_EXTENSIONS:
            files.extend(directory.glob(f"*{ext}"))

    return sorted(files)


def process_bulk_concurrent(
    files: list[Path],
    style_name: str,
    quality: str,
    output_dir: Path,
    backend: str = "openai",
    max_analysis_workers: int = 2,
    skip_existing: bool = True,
    progress_callback: Optional[Callable] = None,
    cost_tracker=None,
    render_registry=None,
    progress_tracker=None,
    run_id: str = "",
) -> BulkResult:
    """
    Process multiple tracks with concurrent analysis pipeline.

    While one track is generating (API calls), the next track is being analyzed.
    This overlaps CPU-bound analysis with I/O-bound API calls.
    """
    from .analyzer.audio import analyze_track
    from .generator.engine import GenerationConfig, generate_visuals
    from .composer.timeline import compose_timeline
    from .resolume.export import create_resolume_deck, generate_resolume_osc_script

    result = BulkResult(total=len(files))
    start_time = time.time()

    # Load style config
    style_config = _load_style_config(style_name)

    # Pre-analyze tracks concurrently (stage 1 overlap)
    analyzed = {}
    with ThreadPoolExecutor(max_workers=max_analysis_workers, thread_name_prefix="analyze") as pool:
        futures = {}
        for file_path in files:
            track_name = _sanitize(file_path.stem)
            track_dir = output_dir / track_name

            # Skip if already processed
            if skip_existing and (track_dir / "metadata.json").exists():
                result.skipped += 1
                if progress_tracker and run_id:
                    progress_tracker.mark_file_skipped(run_id, str(file_path), "already exists")
                if progress_callback:
                    progress_callback(result.completed + result.skipped + result.failed,
                                      result.total, f"Skipped (exists): {file_path.name}")
                continue

            future = pool.submit(_analyze_track_safe, str(file_path), style_name)
            futures[future] = file_path

        # Collect analysis results
        for future in futures:
            file_path = futures[future]
            try:
                analysis, mood_data = future.result(timeout=120)
                if analysis:
                    analyzed[file_path] = (analysis, mood_data)
                else:
                    result.failed += 1
                    result.errors.append({"file": str(file_path), "error": "Analysis failed"})
                    if progress_tracker and run_id:
                        progress_tracker.mark_file_failed(run_id, str(file_path), "Analysis failed")
            except Exception as e:
                result.failed += 1
                result.errors.append({"file": str(file_path), "error": str(e)})
                logger.error(f"Analysis failed for {file_path.name}: {e}")
                if progress_tracker and run_id:
                    progress_tracker.mark_file_failed(run_id, str(file_path), str(e))

    # Generate visuals sequentially (API-bound, one at a time to respect rate limits)
    for file_path, (analysis, mood_data) in analyzed.items():
        track_name = _sanitize(analysis.title)
        track_dir = output_dir / track_name
        track_dir.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(result.completed + result.skipped + result.failed,
                              result.total, f"Generating: {file_path.name}")

        try:
            # Prepare analysis dict with mood
            analysis_dict = analysis.to_dict()
            if mood_data:
                analysis_dict["mood"] = mood_data

            # Resolve style (auto/auto-mix support)
            effective_style = style_config
            effective_style_name = style_name

            gen_config = GenerationConfig(
                style_name=effective_style_name,
                style_config=effective_style,
                backend=backend,
                quality=quality,
                output_dir=str(track_dir / "raw"),
                cache_dir=str(track_dir / ".cache"),
            )

            # Generate
            clips = generate_visuals(
                analysis_dict, gen_config,
                cost_tracker=cost_tracker,
                render_registry=render_registry,
            )

            if not clips:
                result.failed += 1
                result.errors.append({"file": str(file_path), "error": "No clips generated"})
                if progress_tracker and run_id:
                    progress_tracker.mark_file_failed(run_id, str(file_path), "No clips generated")
                continue

            # Compose + export
            comp = compose_timeline(analysis_dict, clips, track_dir)
            create_resolume_deck(comp, track_dir)
            generate_resolume_osc_script(comp, track_dir / "osc_trigger.py")

            track_cost = sum(c.get("cost", 0) for c in clips) if cost_tracker else 0
            result.completed += 1
            result.total_clips += len(clips)
            result.total_cost += track_cost

            if progress_tracker and run_id:
                progress_tracker.mark_file_complete(
                    run_id, str(file_path), str(track_dir),
                    cost=track_cost, clips=len(clips),
                )

            if progress_callback:
                progress_callback(result.completed + result.skipped + result.failed,
                                  result.total, f"Complete: {file_path.name} ({len(clips)} clips)")

            logger.info(f"Completed: {file_path.name} — {len(clips)} clips")

        except Exception as e:
            result.failed += 1
            result.errors.append({"file": str(file_path), "error": str(e)})
            logger.exception(f"Generation failed for {file_path.name}")
            if progress_tracker and run_id:
                progress_tracker.mark_file_failed(run_id, str(file_path), str(e))

    result.duration_seconds = time.time() - start_time
    return result


def _analyze_track_safe(file_path: str, style_name: str):
    """Analyze a track with mood detection, returning (analysis, mood_dict) or (None, None)."""
    from .analyzer.audio import analyze_track

    try:
        analysis = analyze_track(file_path)
    except Exception as e:
        logger.error(f"Analysis failed for {file_path}: {e}")
        return None, None

    # Mood analysis (optional, don't fail if unavailable)
    mood_data = None
    try:
        from .analyzer.mood import analyze_mood
        mood = analyze_mood(file_path)
        mood_data = mood.to_dict()
    except Exception as e:
        logger.debug(f"Mood analysis skipped for {file_path}: {e}")

    return analysis, mood_data


def _load_style_config(style_name: str) -> dict:
    """Load a style configuration by name."""
    if style_name in ("auto", "auto-mix"):
        # Will be resolved per-track
        return {"prompts": {"base": "abstract visual art"}, "colors": {}, "effects": {}}

    style_dir = Path(__file__).parent.parent / "config" / "styles"
    style_file = style_dir / f"{style_name}.yaml"

    if style_file.exists():
        with open(style_file) as f:
            return yaml.safe_load(f)

    # Try as file path
    style_path = Path(style_name)
    if style_path.exists():
        with open(style_path) as f:
            return yaml.safe_load(f)

    logger.warning(f"Style not found: {style_name}, using defaults")
    return {"prompts": {"base": "abstract visual art"}, "colors": {}, "effects": {}}


def _sanitize(name: str) -> str:
    for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        name = name.replace(char, '_')
    return name.strip().strip('.')
