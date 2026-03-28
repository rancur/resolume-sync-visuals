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
    bpm_override: Optional[float] = None,
) -> TrackAnalysis:
    """
    Full analysis of an audio track.

    Args:
        file_path: Path to audio file (FLAC, MP3, WAV, etc.)
        target_sr: Sample rate for analysis
        phrase_beats: Override auto-detected phrase length (default: auto)
        bpm_override: Override BPM detection with a known value

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
    # Priority: explicit override > file tags > librosa detection
    if bpm_override is None:
        # Try reading BPM from file metadata tags (DJ-verified, more accurate)
        try:
            from ..scanner import read_bpm_from_tags
            tag_bpm = read_bpm_from_tags(str(file_path))
            if tag_bpm and tag_bpm > 0:
                bpm_override = tag_bpm
                logger.info(f"  BPM from file tags: {tag_bpm:.1f}")
        except Exception as e:
            logger.debug(f"  Could not read BPM from tags: {e}")

    if bpm_override:
        # Use specified BPM, track beats at that tempo
        bpm = bpm_override
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames", bpm=bpm)
        logger.info(f"  Using BPM override: {bpm:.1f}")
    else:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        if hasattr(tempo, '__len__'):
            bpm = float(tempo[0]) if len(tempo) > 0 else float(tempo)
        else:
            bpm = float(tempo)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # Fix half/third-tempo detection common in electronic music
    # librosa often detects at half or 2/3 tempo for fast genres
    # Strategy: if doubling puts us in a common EDM range (120-180), prefer the double
    doubled = bpm * 2
    tripled_half = bpm * 1.5  # For 2/3 detection (e.g., 117 * 1.5 = 175)

    corrected = False
    if bpm < 95 and 140 <= doubled <= 200:
        # Clear half-tempo (e.g., 86 → 172 for DnB)
        bpm = doubled
        corrected = True
    elif 100 <= bpm <= 125 and 140 <= tripled_half <= 190:
        # Possible 2/3 detection (e.g., 117 → 175 for DnB)
        # Only correct if the 1.5x value falls in a very common EDM range
        # and original is in an uncommon range (100-125 is ambiguous)
        # Don't auto-correct — this range is valid for many genres
        pass

    if corrected:
        logger.info(f"  Corrected tempo: {bpm/2:.1f} → {bpm:.1f} BPM")
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames", bpm=bpm)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

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
    Label phrases based on energy dynamics using EDM structural patterns.
    Uses energy transitions (rising/falling) rather than just absolute levels.
    Classic EDM: intro -> buildup -> drop -> breakdown -> buildup -> drop -> outro
    """
    if not phrases:
        return

    energies = [p.energy for p in phrases]
    max_e = max(energies) if energies else 1.0
    min_e = min(energies) if energies else 0.0
    range_e = max_e - min_e if max_e > min_e else 1.0

    # Normalize energies 0-1
    ne = [(e - min_e) / range_e for e in energies]
    n = len(phrases)
    if n == 0:
        return

    # Compute energy deltas
    deltas = [0.0] + [ne[i] - ne[i - 1] for i in range(1, n)]

    labels = [""] * n

    # Mark first and last
    labels[0] = "intro"
    if n > 1:
        labels[-1] = "outro"

    # Find energy peaks (drops) and valleys (breakdowns)
    for i in range(1, n - 1):
        prev_e, curr_e, next_e = ne[i - 1], ne[i], ne[i + 1]
        if curr_e >= prev_e and curr_e >= next_e and curr_e > 0.6:
            labels[i] = "drop"
        elif curr_e <= prev_e and curr_e <= next_e and curr_e < 0.4:
            labels[i] = "breakdown"

    # Extend sustained high energy adjacent to drops
    for i in range(1, n - 1):
        if labels[i] == "" and ne[i] > 0.65:
            if (labels[i - 1] == "drop") or (labels[i + 1] == "drop"):
                labels[i] = "drop"

    # Fill in buildups, breakdowns, and remaining labels
    for i in range(1, n - 1):
        if labels[i] != "":
            continue
        pos = i / max(n - 1, 1)

        # Rising energy toward a drop = buildup
        if deltas[i] > 0.05:
            upcoming_drop = any(
                labels[j] == "drop"
                for j in range(i + 1, min(i + 3, n))
                if labels[j] != ""
            )
            if upcoming_drop or ne[i] > 0.4:
                labels[i] = "buildup"
                continue

        # Falling energy after a drop = breakdown
        if deltas[i] < -0.05:
            prev_drop = any(
                labels[j] == "drop"
                for j in range(max(0, i - 2), i)
                if labels[j] != ""
            )
            if prev_drop:
                labels[i] = "breakdown"
                continue

        # Position-based fallback
        if pos < 0.15:
            labels[i] = "intro"
        elif pos > 0.85:
            labels[i] = "outro"
        elif ne[i] > 0.6:
            labels[i] = "drop"
        elif ne[i] < 0.35:
            labels[i] = "breakdown"
        else:
            labels[i] = "buildup"

    # Handle any remaining unlabeled
    for i in range(n):
        if labels[i] == "":
            labels[i] = "buildup" if ne[i] > 0.4 else "breakdown"

    for phrase, label in zip(phrases, labels):
        phrase.label = label
