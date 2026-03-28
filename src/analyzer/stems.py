"""
Audio stem separation and sonic event detection.

Separates audio into stems (drums, bass, other/synths, vocals) using Demucs,
analyzes each stem independently, detects sonic events, and creates a per-frame
timeline at configurable FPS for visual synchronization.
"""
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import librosa
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Stem names produced by htdemucs
STEM_NAMES = ["drums", "bass", "other", "vocals"]

# Frequency band definitions (Hz)
FREQUENCY_BANDS = {
    "sub_bass": (20, 60),
    "bass": (60, 250),
    "low_mid": (250, 500),
    "mid": (500, 2000),
    "high_mid": (2000, 6000),
    "high": (6000, 16000),
}

# Spectral character thresholds
_BRIGHT_CENTROID_THRESHOLD = 4000  # Hz — above this = bright
_DARK_CENTROID_THRESHOLD = 1500   # Hz — below this = dark
_GRITTY_FLATNESS_THRESHOLD = 0.3  # flatness above this + moderate centroid = gritty
_NOISY_FLATNESS_THRESHOLD = 0.6   # very high flatness = noisy
_CLEAN_FLATNESS_THRESHOLD = 0.1   # very low flatness = clean


@dataclass
class SonicEvent:
    time: float           # seconds
    duration: float       # seconds
    stem: str             # drums/bass/other/vocals
    event_type: str       # onset/stab/transient/sustained/buildup/drop/sweep/silence
    intensity: float      # 0-1
    frequency_band: str   # sub_bass/bass/low_mid/mid/high_mid/high
    spectral_character: str  # bright/dark/gritty/clean/noisy
    description: str      # "gritty synth stab", "kick hit", "vocal chop"


def _json_default(obj):
    """JSON serializer for numpy types."""
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def separate_stems(audio_path: str, model_name: str = "htdemucs") -> tuple[dict, int]:
    """
    Separate audio into stems using Demucs.

    Args:
        audio_path: Path to audio file.
        model_name: Demucs model name (default: htdemucs).

    Returns:
        Tuple of (dict mapping stem name to numpy array, sample rate).
        Each array is mono float32.
    """
    import torch
    import torchaudio
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")
    logger.info(f"Loading Demucs model '{model_name}' on {device}")

    model = get_model(model_name)
    model.to(device)

    # Load audio as torch tensor
    waveform, sr = torchaudio.load(str(audio_path))

    # Resample to model's sample rate if needed
    if sr != model.samplerate:
        logger.info(f"  Resampling {sr} -> {model.samplerate}")
        resampler = torchaudio.transforms.Resample(sr, model.samplerate)
        waveform = resampler(waveform)
        sr = model.samplerate

    # Demucs expects (batch, channels, samples)
    ref = waveform.mean(0)
    waveform = (waveform - ref.mean()) / ref.std()
    waveform = waveform.unsqueeze(0).to(device)

    logger.info(f"  Separating stems...")
    with torch.no_grad():
        sources = apply_model(model, waveform, device=device)

    # sources shape: (batch, n_sources, channels, samples)
    sources = sources[0].cpu().numpy()

    stems = {}
    for i, name in enumerate(model.sources):
        # Convert to mono by averaging channels
        stem_audio = sources[i].mean(axis=0).astype(np.float32)
        stems[name] = stem_audio

    logger.info(f"  Separated into {len(stems)} stems: {list(stems.keys())}")
    return stems, sr


def classify_spectral_character(centroid: float, flatness: float) -> str:
    """
    Classify spectral character from centroid (Hz) and flatness (0-1).

    Returns one of: bright, dark, gritty, clean, noisy.
    """
    if flatness > _NOISY_FLATNESS_THRESHOLD:
        return "noisy"
    if flatness > _GRITTY_FLATNESS_THRESHOLD and centroid < _BRIGHT_CENTROID_THRESHOLD:
        return "gritty"
    if centroid > _BRIGHT_CENTROID_THRESHOLD:
        return "bright"
    if centroid < _DARK_CENTROID_THRESHOLD:
        return "dark"
    if flatness < _CLEAN_FLATNESS_THRESHOLD:
        return "clean"
    return "clean"


def _dominant_frequency_band(audio: np.ndarray, sr: int) -> str:
    """Determine the dominant frequency band of an audio segment."""
    if len(audio) < 512:
        return "mid"

    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)

    max_energy = 0.0
    dominant = "mid"
    for band_name, (lo, hi) in FREQUENCY_BANDS.items():
        mask = (freqs >= lo) & (freqs < hi)
        energy = np.sum(fft[mask] ** 2) if mask.any() else 0.0
        if energy > max_energy:
            max_energy = energy
            dominant = band_name

    return dominant


def _compute_band_energies(audio: np.ndarray, sr: int) -> dict[str, float]:
    """Compute energy per frequency band, normalized 0-1."""
    if len(audio) < 512:
        return {name: 0.0 for name in FREQUENCY_BANDS}

    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)

    energies = {}
    for band_name, (lo, hi) in FREQUENCY_BANDS.items():
        mask = (freqs >= lo) & (freqs < hi)
        energies[band_name] = float(np.sum(fft[mask] ** 2)) if mask.any() else 0.0

    # Normalize
    max_e = max(energies.values()) if energies else 1.0
    if max_e > 0:
        energies = {k: v / max_e for k, v in energies.items()}

    return energies


def find_active_regions(rms: np.ndarray, sr: int, hop_length: int,
                        threshold_factor: float = 0.15) -> list[tuple[float, float]]:
    """
    Find regions where the stem is active (above adaptive RMS threshold).

    Args:
        rms: RMS energy array (1D).
        sr: Sample rate.
        hop_length: Hop length used for RMS computation.
        threshold_factor: Fraction of max RMS to use as threshold.

    Returns:
        List of (start_time, end_time) tuples in seconds.
    """
    if len(rms) == 0:
        return []

    threshold = np.max(rms) * threshold_factor
    active = rms > threshold

    regions = []
    in_region = False
    start = 0

    for i, is_active in enumerate(active):
        if is_active and not in_region:
            start = i
            in_region = True
        elif not is_active and in_region:
            start_t = librosa.frames_to_time(start, sr=sr, hop_length=hop_length)
            end_t = librosa.frames_to_time(i, sr=sr, hop_length=hop_length)
            regions.append((float(start_t), float(end_t)))
            in_region = False

    # Close final region
    if in_region:
        start_t = librosa.frames_to_time(start, sr=sr, hop_length=hop_length)
        end_t = librosa.frames_to_time(len(rms) - 1, sr=sr, hop_length=hop_length)
        regions.append((float(start_t), float(end_t)))

    return regions


def analyze_stem(audio: np.ndarray, sr: int, name: str) -> dict:
    """
    Full analysis of one stem: RMS, onsets, spectral features, frequency bands, active regions.

    Args:
        audio: Mono audio array (float32).
        sr: Sample rate.
        name: Stem name (drums/bass/other/vocals).

    Returns:
        Dict with keys: name, rms, rms_times, onsets, onset_strengths,
        spectral_centroid, spectral_flatness, band_energies, active_regions,
        mean_centroid, mean_flatness, spectral_character.
    """
    hop_length = 512

    # RMS energy
    rms = librosa.feature.rms(y=audio, frame_length=2048, hop_length=hop_length)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

    # Normalize RMS
    rms_max = rms.max()
    rms_norm = rms / rms_max if rms_max > 0 else rms

    # Onset detection
    onset_env = librosa.onset.onset_strength(y=audio, sr=sr, hop_length=hop_length)
    onset_frames = librosa.onset.onset_detect(
        y=audio, sr=sr, hop_length=hop_length, onset_envelope=onset_env
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)

    # Onset strengths at detected onsets
    onset_strengths = onset_env[onset_frames] if len(onset_frames) > 0 else np.array([])
    if len(onset_strengths) > 0:
        os_max = onset_strengths.max()
        if os_max > 0:
            onset_strengths = onset_strengths / os_max

    # Spectral centroid and flatness
    spec_centroid = librosa.feature.spectral_centroid(y=audio, sr=sr, hop_length=hop_length)[0]
    spec_flatness = librosa.feature.spectral_flatness(y=audio, hop_length=hop_length)[0]

    mean_centroid = float(np.mean(spec_centroid))
    mean_flatness = float(np.mean(spec_flatness))

    # Band energies (overall)
    band_energies = _compute_band_energies(audio, sr)

    # Active regions
    active_regions = find_active_regions(rms_norm, sr, hop_length)

    # Spectral character
    character = classify_spectral_character(mean_centroid, mean_flatness)

    logger.info(
        f"  {name}: {len(onset_times)} onsets, character={character}, "
        f"centroid={mean_centroid:.0f}Hz, flatness={mean_flatness:.3f}, "
        f"{len(active_regions)} active regions"
    )

    return {
        "name": name,
        "rms": rms_norm,
        "rms_times": rms_times,
        "onsets": onset_times.tolist(),
        "onset_strengths": onset_strengths.tolist() if isinstance(onset_strengths, np.ndarray) else onset_strengths,
        "spectral_centroid": spec_centroid,
        "spectral_flatness": spec_flatness,
        "band_energies": band_energies,
        "active_regions": active_regions,
        "mean_centroid": mean_centroid,
        "mean_flatness": mean_flatness,
        "spectral_character": character,
        "sr": sr,
        "hop_length": hop_length,
    }


def _make_description(stem: str, event_type: str, character: str, band: str) -> str:
    """Generate a human-readable description of a sonic event."""
    stem_labels = {
        "drums": {"onset": "drum hit", "transient": "percussive hit", "sustained": "drum roll"},
        "bass": {"onset": "bass note", "transient": "bass pluck", "sustained": "bass drone",
                 "stab": "bass stab"},
        "other": {"onset": "synth hit", "transient": "synth stab", "sustained": "synth pad",
                  "stab": "synth stab", "sweep": "synth sweep", "buildup": "riser",
                  "drop": "synth drop"},
        "vocals": {"onset": "vocal chop", "transient": "vocal hit", "sustained": "vocal phrase",
                   "stab": "vocal stab"},
    }

    base = stem_labels.get(stem, {}).get(event_type, f"{stem} {event_type}")
    return f"{character} {base}" if character not in ("clean",) else base


def detect_sonic_events(stem_analysis: dict) -> list[SonicEvent]:
    """
    Detect specific sonic events from analyzed stem data.

    Detects: onsets, stabs (short high-energy), transients, sustained notes,
    buildups (rising energy), drops (sudden energy increase), sweeps (moving centroid),
    silence regions.

    Args:
        stem_analysis: Dict returned by analyze_stem().

    Returns:
        List of SonicEvent instances sorted by time.
    """
    name = stem_analysis["name"]
    onsets = stem_analysis["onsets"]
    onset_strengths = stem_analysis["onset_strengths"]
    rms = stem_analysis["rms"]
    rms_times = stem_analysis["rms_times"]
    spec_centroid = stem_analysis["spectral_centroid"]
    spec_flatness = stem_analysis["spectral_flatness"]
    sr = stem_analysis["sr"]
    hop_length = stem_analysis["hop_length"]
    character = stem_analysis["spectral_character"]

    events = []

    # 1. Onset-based events
    for i, onset_time in enumerate(onsets):
        strength = float(onset_strengths[i]) if i < len(onset_strengths) else 0.5

        # Find the frame index for this onset
        frame_idx = librosa.time_to_frames(onset_time, sr=sr, hop_length=hop_length)
        frame_idx = min(frame_idx, len(rms) - 1)

        # Look ahead to determine duration and type
        # Check if energy stays high (sustained) or drops quickly (transient/stab)
        lookahead = min(20, len(rms) - frame_idx)  # ~0.5s at 512 hop / 44100
        if lookahead > 2:
            segment_rms = rms[frame_idx:frame_idx + lookahead]
            peak_rms = segment_rms[0] if len(segment_rms) > 0 else 0
            tail_rms = np.mean(segment_rms[-3:]) if len(segment_rms) >= 3 else 0

            if peak_rms > 0.5 and tail_rms < peak_rms * 0.3:
                # Fast decay = stab or transient
                if strength > 0.7:
                    event_type = "stab"
                    duration = float(lookahead * hop_length / sr * 0.3)
                else:
                    event_type = "transient"
                    duration = float(lookahead * hop_length / sr * 0.2)
            elif tail_rms > peak_rms * 0.6:
                event_type = "sustained"
                duration = float(lookahead * hop_length / sr)
            else:
                event_type = "onset"
                duration = float(hop_length / sr)
        else:
            event_type = "onset"
            duration = float(hop_length / sr)

        # Determine frequency band from spectral centroid at this frame
        centroid_val = float(spec_centroid[frame_idx]) if frame_idx < len(spec_centroid) else 1000
        flatness_val = float(spec_flatness[frame_idx]) if frame_idx < len(spec_flatness) else 0.1
        local_character = classify_spectral_character(centroid_val, flatness_val)

        # Map centroid to frequency band
        band = "mid"
        for band_name, (lo, hi) in FREQUENCY_BANDS.items():
            if lo <= centroid_val < hi:
                band = band_name
                break
        if centroid_val >= 6000:
            band = "high"

        desc = _make_description(name, event_type, local_character, band)
        events.append(SonicEvent(
            time=float(onset_time),
            duration=duration,
            stem=name,
            event_type=event_type,
            intensity=strength,
            frequency_band=band,
            spectral_character=local_character,
            description=desc,
        ))

    # 2. Buildup detection — rising RMS over several seconds
    window_frames = int(2.0 * sr / hop_length)  # 2 second window
    for i in range(0, len(rms) - window_frames, window_frames // 2):
        segment = rms[i:i + window_frames]
        if len(segment) < 4:
            continue
        # Check for consistent rise
        first_quarter = np.mean(segment[:len(segment) // 4])
        last_quarter = np.mean(segment[-len(segment) // 4:])
        if last_quarter > first_quarter * 2.0 and last_quarter > 0.3:
            t = float(rms_times[i])
            dur = float(rms_times[min(i + window_frames, len(rms_times) - 1)] - t)
            events.append(SonicEvent(
                time=t, duration=dur, stem=name, event_type="buildup",
                intensity=float(last_quarter),
                frequency_band=_dominant_frequency_band(
                    np.zeros(1), sr) if len(rms) == 0 else "mid",
                spectral_character=character,
                description=_make_description(name, "buildup", character, "mid"),
            ))

    # 3. Drop detection — sudden large energy increase
    for i in range(1, len(rms)):
        if rms[i] > 0.6 and (i == 0 or rms[i - 1] < 0.3):
            t = float(rms_times[i])
            events.append(SonicEvent(
                time=t, duration=0.1, stem=name, event_type="drop",
                intensity=float(rms[i]),
                frequency_band="mid",
                spectral_character=character,
                description=_make_description(name, "drop", character, "mid"),
            ))

    # 4. Silence detection — extended quiet regions
    active_regions = stem_analysis["active_regions"]
    if active_regions:
        # Check gaps between active regions
        for i in range(1, len(active_regions)):
            gap_start = active_regions[i - 1][1]
            gap_end = active_regions[i][0]
            gap_dur = gap_end - gap_start
            if gap_dur > 1.0:  # Silence > 1 second
                events.append(SonicEvent(
                    time=gap_start, duration=gap_dur, stem=name,
                    event_type="silence", intensity=0.0,
                    frequency_band="mid", spectral_character="clean",
                    description=f"{name} silence",
                ))

    # Sort by time
    events.sort(key=lambda e: e.time)
    return events


def _resample_to_fps(values: np.ndarray, times: np.ndarray,
                     fps: float, total_frames: int) -> list[float]:
    """Resample a time-series to a fixed FPS grid using interpolation."""
    if len(values) == 0 or len(times) == 0:
        return [0.0] * total_frames

    frame_times = np.linspace(0, times[-1], total_frames)
    interpolated = np.interp(frame_times, times, values)
    return [float(v) for v in interpolated]


def create_event_timeline(audio_path: str, fps: float = 30.0,
                          model_name: str = "htdemucs") -> dict:
    """
    Full pipeline: separate stems, analyze each, detect events, build per-frame timeline.

    Args:
        audio_path: Path to audio file.
        fps: Frames per second for per-frame data (default: 30).
        model_name: Demucs model name.

    Returns:
        Complete timeline dict with events, per-frame data, and summary.
    """
    audio_path = str(audio_path)
    logger.info(f"Creating event timeline for: {audio_path}")

    # Step 1: Separate stems
    stems, sr = separate_stems(audio_path, model_name=model_name)

    # Compute duration
    any_stem = next(iter(stems.values()))
    duration = len(any_stem) / sr
    total_frames = int(duration * fps)

    logger.info(f"  Duration: {duration:.1f}s, Frames: {total_frames}")

    # Step 2: Analyze each stem
    all_analyses = {}
    for stem_name, stem_audio in stems.items():
        all_analyses[stem_name] = analyze_stem(stem_audio, sr, stem_name)

    # Step 3: Detect sonic events per stem
    all_events = []
    events_per_stem = {}
    for stem_name, analysis in all_analyses.items():
        events = detect_sonic_events(analysis)
        all_events.extend(events)
        events_per_stem[stem_name] = len(events)

    all_events.sort(key=lambda e: e.time)

    # Step 4: Build per-frame data
    per_frame_stems = {}
    for stem_name, analysis in all_analyses.items():
        rms = analysis["rms"]
        rms_times = analysis["rms_times"]
        centroid = analysis["spectral_centroid"]

        # Normalize centroid to 0-1 for "brightness"
        centroid_max = centroid.max() if len(centroid) > 0 else 1.0
        brightness = centroid / centroid_max if centroid_max > 0 else centroid

        per_frame_stems[stem_name] = {
            "energy": _resample_to_fps(rms, rms_times, fps, total_frames),
            "brightness": _resample_to_fps(brightness, rms_times, fps, total_frames),
        }

    timeline = {
        "audio_file": Path(audio_path).name,
        "duration": round(duration, 2),
        "sample_rate": sr,
        "stems": list(stems.keys()),
        "events": [asdict(e) for e in all_events],
        "per_frame_data": {
            "fps": fps,
            "total_frames": total_frames,
            "stems": per_frame_stems,
        },
        "summary": {
            "total_events": len(all_events),
            "events_per_stem": events_per_stem,
        },
    }

    logger.info(
        f"  Timeline complete: {len(all_events)} events, "
        f"{total_frames} frames across {len(stems)} stems"
    )

    return timeline


def save_timeline(timeline: dict, output_path: str | Path):
    """Save timeline dict to JSON file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(timeline, f, indent=2, default=_json_default)
    logger.info(f"  Saved timeline to {output_path}")
