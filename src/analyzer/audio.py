"""
Music analysis pipeline — BPM, beats, phrases, segments, energy.
Produces a structured analysis dict that drives the visual generator.
"""
import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import librosa
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


@dataclass
class Beat:
    time: float  # seconds
    strength: float  # 0-1 relative strength
    is_downbeat: bool = False


@dataclass
class Phrase:
    start: float  # seconds
    end: float  # seconds
    beats: int  # number of beats in phrase
    energy: float  # average energy 0-1
    spectral_centroid: float  # brightness indicator
    label: str = ""  # e.g. "intro", "buildup", "drop", "breakdown"


@dataclass
class TrackAnalysis:
    file_path: str
    title: str
    duration: float  # seconds
    bpm: float
    time_signature: int  # beats per bar (usually 4)
    beats: list[Beat] = field(default_factory=list)
    phrases: list[Phrase] = field(default_factory=list)
    # Per-beat energy envelope (normalized 0-1)
    energy_envelope: list[float] = field(default_factory=list)
    # Spectral features per phrase
    key: str = ""
    genre_hint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, path: Optional[Path] = None) -> str:
        data = self.to_dict()
        text = json.dumps(data, indent=2, default=_json_default)
        if path:
            path.write_text(text)
        return text

    @property
    def beat_duration(self) -> float:
        """Duration of one beat in seconds."""
        return 60.0 / self.bpm

    @property
    def bar_duration(self) -> float:
        """Duration of one bar in seconds."""
        return self.beat_duration * self.time_signature

    @property
    def phrase_duration_beats(self) -> int:
        """Typical phrase length in beats (usually 16 or 32 for EDM)."""
        if not self.phrases:
            return 16
        lengths = [p.beats for p in self.phrases]
        # Most common phrase length
        from collections import Counter
        return Counter(lengths).most_common(1)[0][0]


def _json_default(obj):
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def analyze_track(
    file_path: str | Path,
    target_sr: int = 22050,
    phrase_beats: Optional[int] = None,
) -> TrackAnalysis:
    """
    Full analysis of an audio track.

    Args:
        file_path: Path to audio file (FLAC, MP3, WAV, etc.)
        target_sr: Sample rate for analysis
        phrase_beats: Override auto-detected phrase length (default: auto)

    Returns:
        TrackAnalysis with beats, phrases, energy data
    """
    file_path = Path(file_path)
    logger.info(f"Analyzing: {file_path.name}")

    # Load audio
    y, sr = librosa.load(str(file_path), sr=target_sr, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)
    logger.info(f"  Duration: {duration:.1f}s, SR: {sr}")

    # BPM and beat tracking
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    if hasattr(tempo, '__len__'):
        bpm = float(tempo[0]) if len(tempo) > 0 else float(tempo)
    else:
        bpm = float(tempo)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # Fix half-tempo detection common in DnB/fast genres
    # If BPM is suspiciously low and doubling puts it in a common EDM range, double it
    if bpm < 100 and bpm * 2 > 140:
        bpm = bpm * 2
        # Re-track at the corrected tempo
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames", bpm=bpm)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        logger.info(f"  Corrected half-tempo: {bpm:.1f} BPM")

    logger.info(f"  BPM: {bpm:.1f}, Beats: {len(beat_times)}")

    # Beat strength via onset envelope
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_at_beats = onset_env[beat_frames] if len(beat_frames) > 0 else np.array([])
    if len(onset_at_beats) > 0:
        onset_max = onset_at_beats.max()
        if onset_max > 0:
            onset_at_beats = onset_at_beats / onset_max
        else:
            onset_at_beats = np.ones_like(onset_at_beats)

    # Downbeat detection (assume 4/4 time for EDM)
    time_sig = 4
    beats = []
    for i, (t, s) in enumerate(zip(beat_times, onset_at_beats)):
        is_downbeat = (i % time_sig == 0)
        beats.append(Beat(time=float(t), strength=float(s), is_downbeat=is_downbeat))

    # Energy envelope (RMS per beat window)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)
    energy_envelope = []
    for bt in beat_times:
        idx = np.argmin(np.abs(rms_times - bt))
        energy_envelope.append(float(rms[idx]))
    if energy_envelope:
        emax = max(energy_envelope)
        if emax > 0:
            energy_envelope = [e / emax for e in energy_envelope]

    # Spectral centroid for brightness
    spec_cent = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    spec_times = librosa.frames_to_time(np.arange(len(spec_cent)), sr=sr)

    # Phrase segmentation
    if phrase_beats is None:
        phrase_beats = _detect_phrase_length(y, sr, bpm, beat_times)
    logger.info(f"  Phrase length: {phrase_beats} beats")

    phrases = _build_phrases(
        beat_times, energy_envelope, spec_cent, spec_times,
        phrase_beats, duration, bpm
    )
    logger.info(f"  Phrases: {len(phrases)}")

    # Label phrases based on energy profile
    _label_phrases(phrases)

    title = file_path.stem.replace("_", " ").replace("-", " ").title()

    analysis = TrackAnalysis(
        file_path=str(file_path),
        title=title,
        duration=duration,
        bpm=bpm,
        time_signature=time_sig,
        beats=beats,
        phrases=phrases,
        energy_envelope=energy_envelope,
    )

    return analysis


def _detect_phrase_length(y, sr, bpm, beat_times) -> int:
    """
    Auto-detect phrase length using structural segmentation.
    EDM typically uses 8, 16, or 32 beat phrases.
    """
    if len(beat_times) < 16:
        return 8

    # Use spectral flux to find major transitions
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)

    # Try to detect repetition structure using beat-synchronous chroma
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    beat_frames = librosa.time_to_frames(beat_times, sr=sr)

    # Beat-sync the chroma
    if len(beat_frames) > 1:
        beat_chroma = librosa.util.sync(chroma, beat_frames, aggregate=np.median)
    else:
        return 16

    # Self-similarity matrix
    n_beats = beat_chroma.shape[1]
    if n_beats < 32:
        return 8

    # Check energy changes at 8, 16, 32 beat boundaries
    best_phrase = 16
    best_score = 0

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    beat_rms = librosa.util.sync(rms.reshape(1, -1), beat_frames, aggregate=np.mean)[0]

    for candidate in [8, 16, 32]:
        if candidate >= n_beats:
            continue
        # Measure energy variance at phrase boundaries
        boundaries = list(range(0, n_beats, candidate))
        if len(boundaries) < 3:
            continue

        boundary_diffs = []
        for b in boundaries[1:]:
            if b < n_beats and b - 1 >= 0:
                diff = abs(float(beat_rms[b]) - float(beat_rms[b - 1]))
                boundary_diffs.append(diff)

        if boundary_diffs:
            score = np.mean(boundary_diffs)
            if score > best_score:
                best_score = score
                best_phrase = candidate

    return best_phrase


def _build_phrases(beat_times, energy_envelope, spec_cent, spec_times,
                   phrase_beats, duration, bpm) -> list[Phrase]:
    """Build phrase objects from beat data."""
    phrases = []
    n_beats = len(beat_times)

    for i in range(0, n_beats, phrase_beats):
        end_idx = min(i + phrase_beats, n_beats)
        start_time = float(beat_times[i])

        if end_idx < n_beats:
            end_time = float(beat_times[end_idx])
        else:
            # Last phrase extends to end of track
            end_time = duration

        # Average energy for this phrase
        phrase_energy = energy_envelope[i:end_idx]
        avg_energy = float(np.mean(phrase_energy)) if phrase_energy else 0.5

        # Average spectral centroid for this phrase
        mask = (spec_times >= start_time) & (spec_times < end_time)
        phrase_spec = spec_cent[mask]
        avg_centroid = float(np.mean(phrase_spec)) if len(phrase_spec) > 0 else 2000.0

        phrases.append(Phrase(
            start=start_time,
            end=end_time,
            beats=end_idx - i,
            energy=avg_energy,
            spectral_centroid=avg_centroid,
            label="",
        ))

    return phrases


def _label_phrases(phrases: list[Phrase]):
    """
    Label phrases based on energy dynamics.
    EDM structure: intro → buildup → drop → breakdown → buildup → drop → outro
    """
    if not phrases:
        return

    energies = [p.energy for p in phrases]
    max_e = max(energies) if energies else 1.0
    min_e = min(energies) if energies else 0.0
    range_e = max_e - min_e if max_e > min_e else 1.0

    # Normalize energies
    norm_energies = [(e - min_e) / range_e for e in energies]

    n = len(phrases)
    for i, (phrase, ne) in enumerate(zip(phrases, norm_energies)):
        # Position in track (0-1)
        pos = i / max(n - 1, 1)

        if pos < 0.1:
            phrase.label = "intro"
        elif pos > 0.9:
            phrase.label = "outro"
        elif ne > 0.75:
            phrase.label = "drop"
        elif ne < 0.35:
            if i > 0 and norm_energies[i - 1] > 0.6:
                phrase.label = "breakdown"
            else:
                phrase.label = "intro" if pos < 0.3 else "breakdown"
        else:
            # Medium energy — check if energy is rising
            if i < n - 1 and norm_energies[i + 1] > ne + 0.15:
                phrase.label = "buildup"
            elif i > 0 and norm_energies[i - 1] > ne:
                phrase.label = "breakdown"
            else:
                phrase.label = "buildup"
