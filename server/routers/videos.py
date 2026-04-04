"""
Video preview proxy — serves generated videos from NAS through the web UI.

GET /api/videos/{track_name}/preview
    Returns the H.264 preview MP4 for a track, streamed from NAS.
    Supports Range headers for seeking in the browser.

GET /api/videos/{track_name}/thumbnail
    Returns the first keyframe image for a track.
"""
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse, Response

from ..config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])

# Cache dir for pulled files
_CACHE_DIR = Path(tempfile.gettempdir()) / "rsv-video-cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# NAS base path for vj-content
_NAS_BASE = "/volume1/vj-content"


def _nas_ssh_args() -> list[str]:
    """Build SSH command prefix from settings."""
    settings = get_settings()
    return [
        "ssh",
        "-p", str(settings.nas_ssh_port),
        "-i", str(settings.nas_ssh_key),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{settings.nas_user}@{settings.nas_host}",
    ]


def _check_nas_file(remote_path: str) -> Optional[int]:
    """Check if a file exists on NAS and return its size, or None."""
    try:
        args = _nas_ssh_args() + [f'stat -c %s "{remote_path}" 2>/dev/null || echo "NOTFOUND"']
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            output = result.stdout.strip()
            if output and output != "NOTFOUND":
                return int(output)
    except Exception as e:
        logger.debug("NAS file check failed for %s: %s", remote_path, e)
    return None


def _stream_from_nas(remote_path: str, offset: int = 0, length: Optional[int] = None):
    """Stream a file from NAS via SSH cat, with optional byte range."""
    if offset > 0 or length is not None:
        # Use dd for byte-range reads
        skip = offset
        if length:
            cmd = f'dd if="{remote_path}" bs=1 skip={skip} count={length} 2>/dev/null'
        else:
            cmd = f'dd if="{remote_path}" bs=1 skip={skip} 2>/dev/null'
    else:
        cmd = f'cat "{remote_path}"'

    args = _nas_ssh_args() + [cmd]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def iterfile():
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.stdout.close()
            proc.wait()

    return iterfile()


def _cached_pull(remote_path: str, cache_key: str) -> Optional[Path]:
    """Pull a file from NAS to local cache. Returns cached path or None."""
    cached = _CACHE_DIR / cache_key
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    try:
        args = _nas_ssh_args() + [f'cat "{remote_path}"']
        with open(cached, "wb") as f:
            result = subprocess.run(
                args, stdout=f, stderr=subprocess.PIPE, timeout=120
            )
        if result.returncode != 0 or not cached.exists() or cached.stat().st_size == 0:
            cached.unlink(missing_ok=True)
            return None
        return cached
    except Exception as e:
        logger.error("Failed to cache NAS file %s: %s", remote_path, e)
        cached.unlink(missing_ok=True)
        return None


@router.get("/{track_name}/preview")
async def get_video_preview(track_name: str, request: Request):
    """Stream the H.264 preview MP4 for a track.

    Supports HTTP Range requests for video seeking.
    The video is served from the NAS path:
        /volume1/vj-content/{track_name}/{track_name}.mp4
    """
    remote_path = f"{_NAS_BASE}/{track_name}/{track_name}.mp4"
    file_size = _check_nas_file(remote_path)

    if file_size is None:
        raise HTTPException(404, f"No preview video found for '{track_name}'")

    # Handle Range header
    range_header = request.headers.get("range")
    if range_header:
        # Parse "bytes=start-end"
        try:
            range_spec = range_header.replace("bytes=", "").strip()
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1
        except (ValueError, IndexError):
            start, end = 0, file_size - 1

        length = end - start + 1
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
            "Cache-Control": "public, max-age=3600",
        }
        return StreamingResponse(
            _stream_from_nas(remote_path, offset=start, length=length),
            status_code=206,
            headers=headers,
            media_type="video/mp4",
        )

    # Full file response
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": "video/mp4",
        "Cache-Control": "public, max-age=3600",
    }
    return StreamingResponse(
        _stream_from_nas(remote_path),
        headers=headers,
        media_type="video/mp4",
    )


@router.get("/{track_name}/thumbnail")
async def get_video_thumbnail(track_name: str):
    """Return the first keyframe image for a track.

    Looks for: /volume1/vj-content/{track_name}/keyframes/segment_000_intro.png
    Falls back to any .png in the keyframes directory.
    """
    # Try the standard intro keyframe first
    candidates = [
        f"{_NAS_BASE}/{track_name}/keyframes/segment_000_intro.png",
        f"{_NAS_BASE}/{track_name}/keyframes/segment_000.png",
    ]

    for remote_path in candidates:
        size = _check_nas_file(remote_path)
        if size and size > 0:
            cache_key = f"{track_name}_thumb.png"
            local = _cached_pull(remote_path, cache_key)
            if local:
                return FileResponse(str(local), media_type="image/png")

    # Fallback: find any png in keyframes dir
    try:
        args = _nas_ssh_args() + [
            f'ls "{_NAS_BASE}/{track_name}/keyframes/"*.png 2>/dev/null | head -1'
        ]
        result = subprocess.run(args, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            remote_path = result.stdout.strip()
            cache_key = f"{track_name}_thumb.png"
            local = _cached_pull(remote_path, cache_key)
            if local:
                return FileResponse(str(local), media_type="image/png")
    except Exception:
        pass

    raise HTTPException(404, f"No thumbnail found for '{track_name}'")


@router.get("/{track_name}/info")
async def get_video_info(track_name: str):
    """Return metadata about available video files for a track."""
    preview_path = f"{_NAS_BASE}/{track_name}/{track_name}.mp4"
    dxv_path = f"{_NAS_BASE}/{track_name}/{track_name}.mov"
    meta_path = f"{_NAS_BASE}/{track_name}/metadata.json"

    preview_size = _check_nas_file(preview_path)
    dxv_size = _check_nas_file(dxv_path)

    result = {
        "track_name": track_name,
        "has_preview": preview_size is not None,
        "has_dxv": dxv_size is not None,
        "preview_size_mb": round(preview_size / (1024 * 1024), 2) if preview_size else None,
        "dxv_size_mb": round(dxv_size / (1024 * 1024), 2) if dxv_size else None,
        "preview_url": f"/api/videos/{track_name}/preview" if preview_size else None,
        "thumbnail_url": f"/api/videos/{track_name}/thumbnail",
    }

    # Try to read metadata
    try:
        args = _nas_ssh_args() + [f'cat "{meta_path}" 2>/dev/null']
        proc = subprocess.run(args, capture_output=True, text=True, timeout=10)
        if proc.returncode == 0 and proc.stdout.strip():
            import json
            result["metadata"] = json.loads(proc.stdout)
    except Exception:
        pass

    return result
