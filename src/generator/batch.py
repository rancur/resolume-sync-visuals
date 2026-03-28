"""
OpenAI Batch API support for image generation at 50% cost savings.

Workflow:
1. Prepare a JSONL file with all image generation requests
2. Upload the file to OpenAI
3. Create a batch with the file ID
4. Poll for completion (or check later)
5. Download results and extract images

Each JSONL line:
{"custom_id": "track_0_phrase_2_kf_1", "method": "POST", "url": "/v1/images/generations",
 "body": {"model": "dall-e-3", "prompt": "...", "n": 1, "size": "1792x1024", "quality": "hd"}}
"""
import base64
import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

import httpx

from .engine import (
    GenerationConfig,
    _build_prompt,
    resolve_phrase_style,
)

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Variation suffixes applied to keyframes beyond the first
_KF_VARIATIONS = [
    ", slightly different angle",
    ", subtle color shift",
    ", camera slowly moving",
    ", gentle perspective change",
]


def _n_keyframes(energy: float, quality: str) -> int:
    """Determine number of keyframes for a phrase based on energy and quality."""
    n = 2 if energy < 0.4 else 3 if energy < 0.7 else 4
    if quality == "draft":
        n = min(n, 2)
    return n


def _dalle_quality(quality: str) -> str:
    """Map GenerationConfig quality to DALL-E quality parameter."""
    return "hd" if quality == "high" else "standard"


def prepare_batch(
    analysis_list: list[dict],
    configs: list[GenerationConfig],
    output_dir: Path,
) -> Path:
    """
    Prepare a JSONL batch file for multiple tracks/phrases.

    Args:
        analysis_list: List of track analysis dicts (each has 'phrases', 'bpm', 'title', etc.)
        configs: List of GenerationConfig, one per track (matched by index).
        output_dir: Directory to write the JSONL file.

    Returns:
        Path to the JSONL file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "batch_requests.jsonl"

    request_count = 0
    with open(jsonl_path, "w") as f:
        for track_idx, (analysis, config) in enumerate(zip(analysis_list, configs)):
            phrases = analysis.get("phrases", [])
            default_style = config.style_config or {}
            prompts = default_style.get("prompts", {})
            colors = default_style.get("colors", {})

            for phrase_idx, phrase in enumerate(phrases):
                phrase_style = resolve_phrase_style(
                    phrase["label"], config.style_overrides, default_style
                )
                phrase_prompts = phrase_style.get("prompts", prompts)
                phrase_colors = phrase_style.get("colors", colors)

                base_prompt = _build_prompt(phrase, phrase_prompts, phrase_colors, config.style_name)
                energy = phrase.get("energy", 0.5)
                n_kf = _n_keyframes(energy, config.quality)

                for kf_idx in range(n_kf):
                    prompt = base_prompt
                    if kf_idx > 0:
                        prompt += _KF_VARIATIONS[kf_idx % len(_KF_VARIATIONS)]

                    # Truncate prompt to DALL-E 3 limit
                    if len(prompt) > 3500:
                        prompt = prompt[:3500]

                    custom_id = f"track_{track_idx}_phrase_{phrase_idx}_kf_{kf_idx}"
                    request = {
                        "custom_id": custom_id,
                        "method": "POST",
                        "url": "/v1/images/generations",
                        "body": {
                            "model": "dall-e-3",
                            "prompt": prompt,
                            "n": 1,
                            "size": "1792x1024",
                            "quality": _dalle_quality(config.quality),
                        },
                    }
                    f.write(json.dumps(request) + "\n")
                    request_count += 1

    logger.info(f"Prepared batch JSONL with {request_count} requests: {jsonl_path}")
    return jsonl_path


def parse_custom_id(custom_id: str) -> dict:
    """
    Parse a custom_id string into its components.

    'track_0_phrase_2_kf_1' -> {'track_idx': 0, 'phrase_idx': 2, 'kf_idx': 1}
    """
    parts = custom_id.split("_")
    # Expected format: track_<N>_phrase_<N>_kf_<N>
    result = {}
    i = 0
    while i < len(parts) - 1:
        if parts[i] == "track":
            result["track_idx"] = int(parts[i + 1])
            i += 2
        elif parts[i] == "phrase":
            result["phrase_idx"] = int(parts[i + 1])
            i += 2
        elif parts[i] == "kf":
            result["kf_idx"] = int(parts[i + 1])
            i += 2
        else:
            i += 1
    return result


def _get_api_key() -> str:
    """Get OpenAI API key from environment."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set. Use `op run` to inject.")
    return key


def _api_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }


def submit_batch(jsonl_path: Path) -> str:
    """
    Upload JSONL file and create a batch.

    Args:
        jsonl_path: Path to the JSONL batch file.

    Returns:
        batch_id string.
    """
    jsonl_path = Path(jsonl_path)
    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")

    api_key = _get_api_key()
    headers_auth = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(timeout=120.0) as client:
        # Step 1: Upload JSONL file
        logger.info(f"Uploading batch file: {jsonl_path}")
        with open(jsonl_path, "rb") as f:
            resp = client.post(
                "https://api.openai.com/v1/files",
                headers=headers_auth,
                files={"file": (jsonl_path.name, f, "application/jsonl")},
                data={"purpose": "batch"},
            )
        resp.raise_for_status()
        file_id = resp.json()["id"]
        logger.info(f"Uploaded file: {file_id}")

        # Step 2: Create batch
        resp = client.post(
            "https://api.openai.com/v1/batches",
            headers=_api_headers(),
            json={
                "input_file_id": file_id,
                "endpoint": "/v1/images/generations",
                "completion_window": "24h",
            },
        )
        resp.raise_for_status()
        batch_data = resp.json()
        batch_id = batch_data["id"]
        logger.info(f"Created batch: {batch_id}")

    return batch_id


def check_batch(batch_id: str) -> dict:
    """
    Check batch status.

    Returns dict with:
        status: str (validating, in_progress, completed, failed, expired, cancelled)
        completed: int - number of completed requests
        failed: int - number of failed requests
        total: int - total requests
        output_file_id: str | None - file ID for results (when completed)
    """
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"https://api.openai.com/v1/batches/{batch_id}",
            headers=_api_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    counts = data.get("request_counts", {})
    return {
        "status": data.get("status", "unknown"),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "total": counts.get("total", 0),
        "output_file_id": data.get("output_file_id"),
        "error_file_id": data.get("error_file_id"),
        "created_at": data.get("created_at"),
        "expires_at": data.get("expires_at"),
    }


def list_batches(limit: int = 20) -> list[dict]:
    """List recent batches from OpenAI."""
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            "https://api.openai.com/v1/batches",
            headers=_api_headers(),
            params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()

    batches = []
    for b in data.get("data", []):
        counts = b.get("request_counts", {})
        batches.append({
            "id": b["id"],
            "status": b.get("status", "unknown"),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "total": counts.get("total", 0),
            "created_at": b.get("created_at"),
            "endpoint": b.get("endpoint", ""),
        })
    return batches


def download_batch_results(batch_id: str, output_dir: Path) -> list[dict]:
    """
    Download completed batch results, save images, return metadata.

    Args:
        batch_id: The OpenAI batch ID.
        output_dir: Directory to save downloaded images.

    Returns:
        List of dicts: [{"custom_id": "...", "image_path": "...", "error": None}, ...]
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get batch status to find output file
    status = check_batch(batch_id)
    if status["status"] != "completed":
        raise RuntimeError(
            f"Batch {batch_id} is not completed (status: {status['status']}). "
            f"Progress: {status['completed']}/{status['total']}"
        )

    output_file_id = status.get("output_file_id")
    if not output_file_id:
        raise RuntimeError(f"Batch {batch_id} has no output file.")

    # Download the output file
    with httpx.Client(timeout=120.0) as client:
        resp = client.get(
            f"https://api.openai.com/v1/files/{output_file_id}/content",
            headers={"Authorization": f"Bearer {_get_api_key()}"},
        )
        resp.raise_for_status()
        output_content = resp.text

    results = []
    for line in output_content.strip().split("\n"):
        if not line.strip():
            continue
        entry = json.loads(line)
        custom_id = entry.get("custom_id", "unknown")
        parsed = parse_custom_id(custom_id)

        result = {"custom_id": custom_id, "image_path": None, "error": None}
        result.update(parsed)

        response = entry.get("response", {})
        if response.get("status_code") == 200:
            body = response.get("body", {})
            image_data = body.get("data", [{}])[0]
            image_url = image_data.get("url")
            image_b64 = image_data.get("b64_json")

            image_filename = f"{custom_id}.png"
            image_path = output_dir / image_filename

            try:
                if image_b64:
                    image_path.write_bytes(base64.b64decode(image_b64))
                elif image_url:
                    with httpx.Client(timeout=120.0) as dl_client:
                        img_resp = dl_client.get(image_url)
                        img_resp.raise_for_status()
                        image_path.write_bytes(img_resp.content)
                else:
                    result["error"] = "No image URL or b64 data in response"
                    results.append(result)
                    continue

                result["image_path"] = str(image_path)
            except Exception as e:
                result["error"] = f"Failed to download image: {e}"
                logger.error(f"Failed to download {custom_id}: {e}")
        else:
            error_body = response.get("body", {})
            error_msg = error_body.get("error", {}).get("message", "Unknown error")
            result["error"] = error_msg
            logger.warning(f"Batch request failed for {custom_id}: {error_msg}")

        results.append(result)

    logger.info(
        f"Downloaded {sum(1 for r in results if r['image_path'])} images, "
        f"{sum(1 for r in results if r['error'])} errors"
    )
    return results


def process_batch_results(
    results: list[dict],
    analysis_list: list[dict],
    configs: list[GenerationConfig],
    cost_tracker=None,
    render_registry=None,
):
    """
    Take downloaded batch images and run the video creation pipeline.

    Groups images by track/phrase, creates beat-synced loops, composes timelines,
    and generates Resolume decks.

    Args:
        results: Output from download_batch_results().
        analysis_list: List of track analysis dicts.
        configs: List of GenerationConfig per track.
        cost_tracker: Optional CostTracker for logging batch costs.
        render_registry: Optional RenderRegistry for deduplication tracking.
    """
    from .engine import _create_beat_synced_loop, _resize_and_crop
    from ..composer.timeline import compose_timeline
    from ..resolume.export import create_resolume_deck, generate_resolume_osc_script
    from PIL import Image

    # Group results by track and phrase
    grouped: dict[int, dict[int, list]] = {}  # track_idx -> phrase_idx -> [results]
    for r in results:
        t_idx = r.get("track_idx", 0)
        p_idx = r.get("phrase_idx", 0)
        grouped.setdefault(t_idx, {}).setdefault(p_idx, []).append(r)

    for track_idx, (analysis, config) in enumerate(zip(analysis_list, configs)):
        phrases = analysis.get("phrases", [])
        bpm = analysis.get("bpm", 120)
        track_name = analysis.get("title", "Unknown")
        output_dir = Path(config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        default_style = config.style_config or {}

        track_phrases = grouped.get(track_idx, {})
        clips = []

        for phrase_idx, phrase in enumerate(phrases):
            phrase_results = track_phrases.get(phrase_idx, [])
            # Sort by kf_idx
            phrase_results.sort(key=lambda r: r.get("kf_idx", 0))

            # Collect successful keyframe paths
            keyframes = []
            for r in phrase_results:
                if r.get("image_path") and Path(r["image_path"]).exists():
                    # Resize/crop to target resolution
                    img = Image.open(r["image_path"])
                    img = _resize_and_crop(img, config.width, config.height)
                    img.save(r["image_path"], "PNG")
                    keyframes.append(Path(r["image_path"]))

            if not keyframes:
                logger.warning(f"No keyframes for track {track_idx} phrase {phrase_idx}, skipping")
                continue

            # Log batch costs (50% discount pricing)
            if cost_tracker:
                dalle_quality = _dalle_quality(config.quality)
                pricing_key = f"dall-e-3:{dalle_quality}:1792x1024:batch"
                for _ in keyframes:
                    cost_tracker.log_call(
                        model=pricing_key,
                        track_name=track_name,
                        phrase_idx=phrase_idx,
                        phrase_label=phrase.get("label", ""),
                        style=config.style_name,
                        backend="openai:batch",
                        quality=config.quality,
                        width=config.width,
                        height=config.height,
                    )

            # Create beat-synced loop
            clip_path = output_dir / f"phrase_{phrase_idx:03d}_{phrase['label']}.mp4"
            phrase_style = resolve_phrase_style(
                phrase["label"], config.style_overrides, default_style
            )
            effects = phrase_style.get("effects", {})

            try:
                _create_beat_synced_loop(
                    keyframes=keyframes,
                    output_path=clip_path,
                    bpm=bpm,
                    phrase=phrase,
                    config=config,
                    effects=effects,
                )
            except Exception as e:
                logger.error(f"Failed to create loop for track {track_idx} phrase {phrase_idx}: {e}")
                continue

            clips.append({
                "phrase_idx": phrase_idx,
                "path": str(clip_path),
                "start": phrase["start"],
                "end": phrase["end"],
                "duration": phrase["end"] - phrase["start"],
                "label": phrase["label"],
                "bpm": bpm,
                "beats": phrase.get("beats", 0),
            })

            # Register in render registry
            if render_registry:
                audio_hash = analysis.get("audio_hash", "")
                if audio_hash:
                    render_hash = render_registry.compute_render_hash(
                        audio_hash=audio_hash,
                        style=config.style_name,
                        quality=config.quality,
                        width=config.width,
                        height=config.height,
                        loop_beats=config.loop_duration_beats,
                        phrase_idx=phrase_idx,
                        backend="openai:batch",
                    )
                    render_registry.start_render(
                        render_hash=render_hash, audio_hash=audio_hash,
                        audio_path=analysis.get("file_path", ""),
                        track_name=track_name,
                        style=config.style_name, quality=config.quality,
                        width=config.width, height=config.height, fps=config.fps,
                        loop_beats=config.loop_duration_beats, backend="openai:batch",
                        phrase_idx=phrase_idx, phrase_label=phrase.get("label", ""),
                    )
                    render_registry.complete_render(
                        render_hash, str(clip_path),
                        cost_usd=0, api_calls=len(keyframes),
                    )

        # Compose timeline and Resolume deck
        if clips:
            track_dir = output_dir.parent
            try:
                composition = compose_timeline(analysis, clips, track_dir)
                create_resolume_deck(composition, track_dir)
                generate_resolume_osc_script(composition, track_dir / "osc_trigger.py")
                logger.info(f"Processed track {track_idx} ({track_name}): {len(clips)} clips")
            except Exception as e:
                logger.error(f"Failed to compose track {track_idx}: {e}")


def estimate_batch_cost(
    analysis_list: list[dict],
    configs: list[GenerationConfig],
) -> dict:
    """
    Estimate batch cost without creating any files.

    Returns:
        {
            "total_requests": int,
            "sync_cost": float,
            "batch_cost": float,
            "savings": float,
            "per_track": [{"track": str, "requests": int, "batch_cost": float}, ...]
        }
    """
    per_track = []
    total_requests = 0

    for track_idx, (analysis, config) in enumerate(zip(analysis_list, configs)):
        phrases = analysis.get("phrases", [])
        track_requests = 0
        for phrase in phrases:
            energy = phrase.get("energy", 0.5)
            track_requests += _n_keyframes(energy, config.quality)

        dalle_quality = _dalle_quality(config.quality)
        sync_price = 0.080 if dalle_quality == "hd" else 0.040
        batch_price = sync_price * 0.5

        per_track.append({
            "track": analysis.get("title", f"Track {track_idx}"),
            "requests": track_requests,
            "sync_cost": track_requests * sync_price,
            "batch_cost": track_requests * batch_price,
        })
        total_requests += track_requests

    total_sync = sum(t["sync_cost"] for t in per_track)
    total_batch = sum(t["batch_cost"] for t in per_track)

    return {
        "total_requests": total_requests,
        "sync_cost": total_sync,
        "batch_cost": total_batch,
        "savings": total_sync - total_batch,
        "per_track": per_track,
    }
