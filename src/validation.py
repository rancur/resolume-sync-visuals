"""
Centralized validation utilities for resolume-sync-visuals.
Validates inputs, outputs, dependencies, and environment before expensive operations.
"""
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating a single video file."""
    path: str
    valid: bool
    errors: list[str] = field(default_factory=list)
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    size_bytes: int = 0


def validate_output_video(
    path: str | Path,
    expected_width: int = 1920,
    expected_height: int = 1080,
    expected_codec: str = "h264",
) -> ValidationResult:
    """Validate a video file using ffprobe.

    Checks:
    - File exists and size > 1KB
    - Valid video codec (h264 by default)
    - Resolution matches expected (1920x1080 by default)
    - Duration > 0
    - Has at least one video stream
    """
    path = Path(path)
    result = ValidationResult(path=str(path), valid=False)

    # Check existence
    if not path.exists():
        result.errors.append("File does not exist")
        return result

    # Check size
    result.size_bytes = path.stat().st_size
    if result.size_bytes <= 1024:
        result.errors.append(f"File too small ({result.size_bytes} bytes, need > 1KB)")
        return result

    # Probe with ffprobe
    try:
        probe_output = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        result.errors.append("ffprobe not found — install ffmpeg")
        return result
    except subprocess.TimeoutExpired:
        result.errors.append("ffprobe timed out")
        return result

    if probe_output.returncode != 0:
        result.errors.append(f"ffprobe failed: {probe_output.stderr.strip()}")
        return result

    try:
        probe = json.loads(probe_output.stdout)
    except json.JSONDecodeError:
        result.errors.append("ffprobe returned invalid JSON")
        return result

    # Find video stream
    video_streams = [
        s for s in probe.get("streams", [])
        if s.get("codec_type") == "video"
    ]

    if not video_streams:
        result.errors.append("No video stream found")
        return result

    vs = video_streams[0]

    # Codec
    result.codec = vs.get("codec_name", "")
    if result.codec != expected_codec:
        result.errors.append(
            f"Unexpected codec: {result.codec} (expected {expected_codec})"
        )

    # Resolution
    result.width = int(vs.get("width", 0))
    result.height = int(vs.get("height", 0))
    if result.width != expected_width or result.height != expected_height:
        result.errors.append(
            f"Resolution mismatch: {result.width}x{result.height} "
            f"(expected {expected_width}x{expected_height})"
        )

    # Duration — check stream duration first, then format duration
    dur_str = vs.get("duration") or probe.get("format", {}).get("duration")
    if dur_str:
        result.duration = float(dur_str)
        if result.duration <= 0:
            result.errors.append(f"Duration is {result.duration}s (must be > 0)")
    else:
        result.errors.append("Could not determine duration")

    result.valid = len(result.errors) == 0
    return result


def validate_directory(
    directory: str | Path,
    expected_width: int = 1920,
    expected_height: int = 1080,
    expected_codec: str = "h264",
) -> dict:
    """Validate all .mp4 files in a directory.

    Returns a summary dict with keys:
    - total: number of .mp4 files found
    - valid: number passing all checks
    - invalid: number failing at least one check
    - total_size_bytes: combined size
    - results: list of ValidationResult dicts
    - invalid_files: list of {path, errors} for failures
    """
    directory = Path(directory)
    mp4_files = sorted(directory.rglob("*.mp4"))

    results = []
    valid_count = 0
    invalid_count = 0
    total_size = 0
    invalid_files = []

    for mp4 in mp4_files:
        vr = validate_output_video(
            mp4,
            expected_width=expected_width,
            expected_height=expected_height,
            expected_codec=expected_codec,
        )
        results.append(vr)
        total_size += vr.size_bytes
        if vr.valid:
            valid_count += 1
        else:
            invalid_count += 1
            invalid_files.append({"path": str(mp4), "errors": vr.errors})

    return {
        "total": len(mp4_files),
        "valid": valid_count,
        "invalid": invalid_count,
        "total_size_bytes": total_size,
        "results": results,
        "invalid_files": invalid_files,
    }


# ---------------------------------------------------------------------------
# Audio file validation
# ---------------------------------------------------------------------------

def validate_audio_file(path: str) -> tuple[bool, str]:
    """
    Check if audio file is valid and readable.

    Returns:
        (ok, error_message) -- ok is True if file is valid, error_message is empty on success.

    Tests: file exists, size > 0, can be loaded by soundfile/librosa (first 1s).
    """
    p = Path(path)

    if not p.exists():
        return False, f"File not found: {path}"

    if not p.is_file():
        return False, f"Not a file: {path}"

    size = p.stat().st_size
    if size == 0:
        return False, f"File is empty (0 bytes): {path}"

    # Quick soundfile probe -- fast header check
    try:
        import soundfile as sf
        info = sf.info(str(p))
        if info.frames == 0:
            return False, f"Audio file has 0 frames: {path}"
        if info.samplerate <= 0:
            return False, f"Invalid sample rate ({info.samplerate}): {path}"
    except Exception:
        # Fall back to librosa for formats soundfile can't handle (e.g. MP3)
        try:
            import librosa
            y, sr = librosa.load(str(p), sr=None, mono=True, duration=1.0)
            if len(y) == 0:
                return False, f"Audio file contains no samples: {path}"
        except Exception as e2:
            return False, f"Cannot read audio file: {e2}"

    return True, ""


# ---------------------------------------------------------------------------
# Style config validation
# ---------------------------------------------------------------------------

def validate_style_config(config: dict) -> tuple[bool, list[str]]:
    """
    Validate style YAML structure.

    Returns:
        (ok, list_of_warnings) -- ok is True if config is usable, warnings list issues.

    Checks: has 'prompts' dict, has 'colors' dict, prompts has 'base' key.
    """
    warnings: list[str] = []

    if not isinstance(config, dict):
        return False, ["Style config is not a dictionary"]

    if "prompts" not in config:
        return False, ["Missing required 'prompts' section"]

    prompts = config["prompts"]
    if not isinstance(prompts, dict):
        return False, ["'prompts' must be a dictionary"]

    if "base" not in prompts:
        warnings.append("Missing 'base' prompt -- generation may use empty prompts for unlabeled phrases")

    # Check for expected phrase prompts
    expected_phrases = ["drop", "buildup", "breakdown", "intro", "outro"]
    for phrase in expected_phrases:
        if phrase not in prompts:
            warnings.append(f"Missing prompt for '{phrase}' -- will fall back to 'base'")

    if "colors" not in config:
        warnings.append("Missing 'colors' section -- default colors will be used")
    elif not isinstance(config["colors"], dict):
        warnings.append("'colors' should be a dictionary")

    # Not a hard failure if we have at least some prompts
    ok = "base" in prompts or len(prompts) > 0
    return ok, warnings


# ---------------------------------------------------------------------------
# Disk space
# ---------------------------------------------------------------------------

def check_disk_space(path: str, required_mb: int = 500) -> tuple[bool, int]:
    """
    Check available disk space at the given path.

    Returns:
        (ok, available_mb) -- ok is True if available_mb >= required_mb.
    """
    try:
        p = Path(path)
        # Walk up to find an existing directory
        check_path = p
        while not check_path.exists():
            check_path = check_path.parent
            if check_path == check_path.parent:
                break

        usage = shutil.disk_usage(str(check_path))
        available_mb = int(usage.free / (1024 * 1024))
        return available_mb >= required_mb, available_mb
    except Exception as e:
        logger.warning(f"Could not check disk space: {e}")
        return False, 0


# ---------------------------------------------------------------------------
# External dependency checks
# ---------------------------------------------------------------------------

def check_dependencies() -> dict:
    """
    Check all required external tools.

    Returns:
        {tool: {available: bool, version: str}} for ffmpeg, ffprobe, python.
    """
    results = {}

    # Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 9)
    results["python"] = {"available": py_ok, "version": py_ver}

    # ffmpeg / ffprobe
    for tool in ("ffmpeg", "ffprobe"):
        tool_path = shutil.which(tool)
        if tool_path:
            try:
                out = subprocess.run(
                    [tool, "-version"],
                    capture_output=True, text=True, timeout=10,
                )
                first_line = out.stdout.strip().split("\n")[0] if out.stdout else ""
                version = (
                    first_line.split("version")[-1].strip().split(" ")[0]
                    if "version" in first_line
                    else "unknown"
                )
                results[tool] = {"available": True, "version": version}
            except Exception:
                results[tool] = {"available": True, "version": "unknown"}
        else:
            results[tool] = {"available": False, "version": ""}

    return results


# ---------------------------------------------------------------------------
# API key validation
# ---------------------------------------------------------------------------

def validate_api_key(backend: str) -> tuple[bool, str]:
    """
    Quick validation of API key format (not a full auth check).

    OpenAI keys start with 'sk-'.
    Replicate tokens start with 'r8_'.

    Returns:
        (ok, message)
    """
    if backend == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            return False, "OPENAI_API_KEY environment variable not set"
        if not key.startswith("sk-"):
            return False, f"OPENAI_API_KEY doesn't start with 'sk-' (got '{key[:6]}...')"
        if len(key) < 20:
            return False, "OPENAI_API_KEY looks too short"
        return True, "OPENAI_API_KEY set and format looks valid"

    elif backend == "replicate":
        key = os.environ.get("REPLICATE_API_TOKEN", "")
        if not key:
            return False, "REPLICATE_API_TOKEN environment variable not set"
        if not key.startswith("r8_"):
            return False, f"REPLICATE_API_TOKEN doesn't start with 'r8_' (got '{key[:6]}...')"
        if len(key) < 20:
            return False, "REPLICATE_API_TOKEN looks too short"
        return True, "REPLICATE_API_TOKEN set and format looks valid"

    else:
        return False, f"Unknown backend: {backend}"


# ---------------------------------------------------------------------------
# Mood model check
# ---------------------------------------------------------------------------

def check_mood_models() -> tuple[bool, str]:
    """
    Check if Essentia mood models are downloaded.

    Returns:
        (ok, message)
    """
    project_root = Path(__file__).parent.parent
    models_dir = project_root / "models" / "mood"

    if not models_dir.exists():
        return False, f"Mood models directory not found: {models_dir}"

    # Check for the embedding model (required)
    emb_model = models_dir / "discogs-effnet-bs64-1.pb"
    if not emb_model.exists():
        return False, f"Embedding model not found: {emb_model.name}"

    # Check for at least one mood model
    mood_models = list(models_dir.glob("mood_*-discogs-effnet-1.pb"))
    if not mood_models:
        return False, "No mood classification models found"

    return True, f"Found embedding model + {len(mood_models)} mood models"
