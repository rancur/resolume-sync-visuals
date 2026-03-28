"""
Extended feature extraction for visual mapping.
Maps audio features to visual parameters.
"""
import logging
from dataclasses import dataclass

import librosa
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class VisualFeatures:
    """Audio features mapped to visual parameters."""
    # Per-beat features (arrays, one per beat)
    beat_intensity: list[float]  # 0-1, maps to visual impact
    beat_brightness: list[float]  # 0-1, maps to color brightness
    beat_warmth: list[float]  # 0-1, spectral balance (warm=low freq dominant)

    # Per-phrase features
    phrase_mood: list[str]  # "dark", "bright", "intense", "calm"
    phrase_complexity: list[float]  # 0-1, spectral complexity

    # Global
    overall_energy: float  # 0-1
    overall_brightness: float  # 0-1
    has_vocals: bool


def extract_features(file_path: str, sr: int = 22050) -> VisualFeatures:
    """Extract visual-mapping features from audio."""
    y, sr = librosa.load(file_path, sr=sr, mono=True)

    # Beat tracking
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # RMS energy per beat
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_frames = np.arange(len(rms))

    beat_intensity = []
    for bf in beat_frames:
        idx = min(bf, len(rms) - 1)
        beat_intensity.append(float(rms[idx]))
    if beat_intensity:
        mx = max(beat_intensity)
        if mx > 0:
            beat_intensity = [b / mx for b in beat_intensity]

    # Spectral centroid for brightness
    spec_cent = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    beat_brightness = []
    for bf in beat_frames:
        idx = min(bf, len(spec_cent) - 1)
        beat_brightness.append(float(spec_cent[idx]))
    if beat_brightness:
        mx = max(beat_brightness)
        if mx > 0:
            beat_brightness = [b / mx for b in beat_brightness]

    # Spectral rolloff for warmth (inverse — more low freq = warmer)
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, roll_percent=0.25)[0]
    beat_warmth = []
    for bf in beat_frames:
        idx = min(bf, len(rolloff) - 1)
        beat_warmth.append(float(rolloff[idx]))
    if beat_warmth:
        mx = max(beat_warmth)
        if mx > 0:
            beat_warmth = [1.0 - (b / mx) for b in beat_warmth]  # Invert

    # Phrase-level features (16-beat chunks)
    phrase_size = 16
    n_beats = len(beat_frames)
    phrase_mood = []
    phrase_complexity = []

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)

    for i in range(0, n_beats, phrase_size):
        end = min(i + phrase_size, n_beats)
        if i >= len(beat_intensity):
            break

        avg_energy = np.mean(beat_intensity[i:end])
        avg_bright = np.mean(beat_brightness[i:end]) if beat_brightness else 0.5

        # Mood from energy + brightness
        if avg_energy > 0.65 and avg_bright > 0.5:
            mood = "intense"
        elif avg_energy > 0.65:
            mood = "dark"
        elif avg_bright > 0.6:
            mood = "bright"
        else:
            mood = "calm"
        phrase_mood.append(mood)

        # Complexity from MFCC variance
        start_frame = beat_frames[i] if i < len(beat_frames) else 0
        end_frame = beat_frames[end - 1] if end - 1 < len(beat_frames) else mfcc.shape[1] - 1
        phrase_mfcc = mfcc[:, start_frame:end_frame + 1]
        complexity = float(np.std(phrase_mfcc)) if phrase_mfcc.size > 0 else 0.5
        phrase_complexity.append(complexity)

    # Normalize complexity
    if phrase_complexity:
        mx = max(phrase_complexity)
        if mx > 0:
            phrase_complexity = [c / mx for c in phrase_complexity]

    # Vocal detection (rough — based on spectral flatness in vocal range)
    spec_flat = librosa.feature.spectral_flatness(y=y)[0]
    has_vocals = float(np.mean(spec_flat)) < 0.15  # Tonal content suggests vocals/melody

    return VisualFeatures(
        beat_intensity=beat_intensity,
        beat_brightness=beat_brightness,
        beat_warmth=beat_warmth,
        phrase_mood=phrase_mood,
        phrase_complexity=phrase_complexity,
        overall_energy=float(np.mean(beat_intensity)) if beat_intensity else 0.5,
        overall_brightness=float(np.mean(beat_brightness)) if beat_brightness else 0.5,
        has_vocals=has_vocals,
    )
