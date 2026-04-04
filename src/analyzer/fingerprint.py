"""
Audio fingerprinting for track identification.

Uses a simple but effective approach: hash the first 30 seconds of decoded audio
PCM data. This provides a stable identifier that's independent of file format,
bitrate, or container metadata.

For more advanced matching (e.g., recognizing songs from short clips),
chromaprint/acoustid could be integrated, but the PCM hash approach works well
for our use case of identifying tracks in a known library.
"""
import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# How many seconds of audio to hash
FINGERPRINT_DURATION_SEC = 30.0

# Sample rate for fingerprinting (resample to this for consistency)
FINGERPRINT_SR = 22050


def fingerprint_audio(
    file_path: str | Path,
    duration: float = FINGERPRINT_DURATION_SEC,
    sr: int = FINGERPRINT_SR,
) -> str:
    """Generate a stable fingerprint hash from audio content.

    Loads the first `duration` seconds at a fixed sample rate, quantizes
    to 16-bit, and returns a SHA-256 hex digest (truncated to 32 chars).

    This is format-agnostic: the same track in FLAC, WAV, or MP3 will
    produce the same fingerprint (within decode precision).

    Args:
        file_path: Path to the audio file.
        duration: Seconds of audio to fingerprint.
        sr: Sample rate to decode at.

    Returns:
        32-character hex string fingerprint.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        RuntimeError: If the file can't be decoded.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    try:
        import librosa
        audio, _ = librosa.load(str(file_path), sr=sr, mono=True, duration=duration)
    except Exception as e:
        raise RuntimeError(f"Failed to decode audio: {e}")

    if len(audio) == 0:
        raise RuntimeError(f"Audio file is empty or unreadable: {file_path}")

    # Quantize to 16-bit int for stable hashing across float precision differences
    audio_int16 = (audio * 32767).astype(np.int16)

    h = hashlib.sha256(audio_int16.tobytes())
    return h.hexdigest()[:32]


def fingerprint_from_array(
    audio: np.ndarray,
    sr: int,
    duration: float = FINGERPRINT_DURATION_SEC,
    target_sr: int = FINGERPRINT_SR,
) -> str:
    """Generate fingerprint from an already-loaded audio array.

    Args:
        audio: Audio samples (mono float32).
        sr: Sample rate of the input audio.
        duration: Seconds to fingerprint.
        target_sr: Target sample rate for consistency.

    Returns:
        32-character hex string fingerprint.
    """
    # Resample if needed
    if sr != target_sr:
        import librosa
        audio = librosa.resample(audio, orig_sr=sr, target_sr=target_sr)
        sr = target_sr

    # Trim to duration
    max_samples = int(duration * sr)
    audio = audio[:max_samples]

    if len(audio) == 0:
        raise RuntimeError("Audio array is empty")

    audio_int16 = (audio * 32767).astype(np.int16)
    h = hashlib.sha256(audio_int16.tobytes())
    return h.hexdigest()[:32]


def compare_fingerprints(fp1: str, fp2: str) -> bool:
    """Check if two fingerprints match exactly."""
    return fp1 == fp2
