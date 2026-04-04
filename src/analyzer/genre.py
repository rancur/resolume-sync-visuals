"""
Genre-aware style auto-selection.

Analyzes audio features (BPM, spectral centroid, onset density, bass energy)
to suggest the best visual style for a track.
"""
import hashlib
import logging
import random

import librosa
import numpy as np

logger = logging.getLogger(__name__)

# Genre-to-style mapping
GENRE_STYLE_MAP: dict[str, list[str]] = {
    "house": ["liquid", "abstract"],
    "trance": ["cosmic", "nature"],
    "dnb": ["glitch", "cyberpunk"],
    "techno": ["minimal", "laser"],
    "hard": ["fire", "laser"],
    "ambient": ["nature", "cosmic"],
}


def get_auto_mix_styles(seed: str | None = None) -> dict:
    """Return style overrides for auto-mix mode.

    Maps phrase labels to style names based on energy characteristics.
    When a seed is provided (e.g. audio file hash), the randomization is
    deterministic so the same track always gets the same mix.

    Args:
        seed: Optional seed string for deterministic randomization.

    Returns:
        Dict mapping phrase labels to style names.
    """
    if seed is not None:
        # Create a deterministic seed from the string
        seed_int = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed_int)
    else:
        rng = random.Random()

    return {
        "drop": rng.choice(["laser", "fire", "glitch"]),
        "buildup": rng.choice(["abstract", "cyberpunk", "fractal"]),
        "breakdown": rng.choice(["nature", "cosmic", "liquid"]),
        "intro": rng.choice(["minimal", "cosmic"]),
        "outro": rng.choice(["minimal", "cosmic"]),
    }


def detect_genre_and_style(file_path: str) -> tuple[str, str]:
    """
    Analyze audio features and return a genre hint plus recommended visual style.

    Mapping logic:
      - BPM 120-135 + steady 4-on-floor kick  -> house  -> liquid or abstract
      - BPM 135-150 + sustained pads + buildups -> trance -> cosmic or nature
      - BPM 160-180 + heavy bass + fast transients -> DnB -> glitch or cyberpunk
      - BPM 128-140 + sparse, minimal          -> techno -> minimal or laser
      - High spectral centroid + lots of transients -> hard/aggressive -> fire or laser
      - Low spectral centroid + smooth          -> ambient/melodic -> nature or cosmic

    Args:
        file_path: Path to an audio file.

    Returns:
        Tuple of (genre_hint, recommended_style).
    """
    logger.info(f"Detecting genre for: {file_path}")

    y, sr = librosa.load(file_path, sr=22050, mono=True)

    # --- Core features ---

    # BPM
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    if hasattr(tempo, "__len__"):
        bpm = float(tempo[0]) if len(tempo) > 0 else float(tempo)
    else:
        bpm = float(tempo)

    # Correct half-tempo detection common in fast electronic genres
    if bpm < 95:
        doubled = bpm * 2
        if 140 <= doubled <= 200:
            bpm = doubled

    # Spectral centroid (brightness) — mean across the whole track, in Hz
    spec_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    mean_centroid = float(np.mean(spec_centroid))

    # Onset density — onsets per second (transient rate)
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr)
    duration = librosa.get_duration(y=y, sr=sr)
    onset_density = len(onset_frames) / max(duration, 1.0)

    # Bass energy ratio — energy below 250 Hz vs. total
    S = np.abs(librosa.stft(y))
    freqs = librosa.fft_frequencies(sr=sr)
    bass_mask = freqs <= 250
    bass_energy = float(np.sum(S[bass_mask, :] ** 2))
    total_energy = float(np.sum(S ** 2))
    bass_ratio = bass_energy / max(total_energy, 1e-10)

    # Spectral flatness — how noise-like vs tonal (lower = more tonal/melodic)
    spec_flat = librosa.feature.spectral_flatness(y=y)[0]
    mean_flatness = float(np.mean(spec_flat))

    # RMS energy variance — indicator of dynamic range / buildups
    rms = librosa.feature.rms(y=y)[0]
    rms_std = float(np.std(rms))

    # Onset strength variance — steady kicks vs varied
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_std = float(np.std(onset_env))

    logger.info(
        f"  BPM={bpm:.1f} centroid={mean_centroid:.0f}Hz "
        f"onset_density={onset_density:.1f}/s bass_ratio={bass_ratio:.3f} "
        f"flatness={mean_flatness:.3f} rms_std={rms_std:.3f}"
    )

    # --- Classification ---
    genre = _classify_genre(
        bpm=bpm,
        mean_centroid=mean_centroid,
        onset_density=onset_density,
        bass_ratio=bass_ratio,
        mean_flatness=mean_flatness,
        rms_std=rms_std,
        onset_std=onset_std,
    )

    styles = GENRE_STYLE_MAP.get(genre, ["abstract"])
    style = styles[0]

    logger.info(f"  Genre: {genre} -> Style: {style}")
    return genre, style


def _classify_genre(
    bpm: float,
    mean_centroid: float,
    onset_density: float,
    bass_ratio: float,
    mean_flatness: float,
    rms_std: float,
    onset_std: float,
) -> str:
    """Score each genre candidate and return the best match."""
    scores: dict[str, float] = {
        "house": 0.0,
        "trance": 0.0,
        "dnb": 0.0,
        "techno": 0.0,
        "hard": 0.0,
        "ambient": 0.0,
    }

    # --- BPM ranges ---
    if 120 <= bpm <= 135:
        scores["house"] += 3.0
        scores["techno"] += 1.0
    if 135 <= bpm <= 150:
        scores["trance"] += 3.0
    if 160 <= bpm <= 180:
        scores["dnb"] += 3.0
    if 128 <= bpm <= 140:
        scores["techno"] += 2.0
    if bpm < 110:
        scores["ambient"] += 2.0
    if bpm > 145:
        scores["hard"] += 1.0

    # --- Spectral centroid (brightness) ---
    if mean_centroid > 3000:
        scores["hard"] += 2.0
        scores["dnb"] += 1.0
    elif mean_centroid < 1500:
        scores["ambient"] += 2.0
        scores["house"] += 0.5
    else:
        scores["trance"] += 0.5
        scores["techno"] += 0.5

    # --- Onset density (transients per second) ---
    if onset_density > 6.0:
        scores["hard"] += 2.0
        scores["dnb"] += 1.5
    elif onset_density < 2.5:
        scores["ambient"] += 1.5
        scores["techno"] += 1.0
    else:
        scores["house"] += 0.5
        scores["trance"] += 0.5

    # --- Bass ratio ---
    if bass_ratio > 0.4:
        scores["dnb"] += 1.5
        scores["house"] += 1.0
    elif bass_ratio < 0.15:
        scores["ambient"] += 1.0
        scores["trance"] += 0.5

    # --- Spectral flatness (tonal vs noisy) ---
    if mean_flatness < 0.05:
        # Very tonal — melodic content
        scores["trance"] += 1.0
        scores["ambient"] += 1.0
    elif mean_flatness > 0.2:
        # Noisy / percussive
        scores["hard"] += 1.0
        scores["techno"] += 0.5

    # --- RMS dynamic range (buildups/drops) ---
    if rms_std > 0.05:
        scores["trance"] += 1.0
    elif rms_std < 0.02:
        scores["techno"] += 1.0
        scores["ambient"] += 0.5

    # --- Onset regularity (steady = 4-on-floor) ---
    if onset_std < np.median(list(scores.values())):
        # Steady, regular onsets
        scores["house"] += 1.0
        scores["techno"] += 0.5

    # Pick the highest-scoring genre
    genre = max(scores, key=lambda g: scores[g])
    return genre
