#!/usr/bin/env python3
"""
Generate synthetic EDM test tracks with realistic structure.
Creates tracks with proper BPM, energy curves, and EDM arrangement.
"""
import numpy as np
import soundfile as sf
from pathlib import Path
import sys


def generate_kick(sr, bpm):
    """Generate a kick drum sound."""
    duration = min(0.15, 60.0 / bpm * 0.4)
    t = np.arange(int(duration * sr)) / sr
    # Pitch sweep from 150Hz down to 50Hz
    freq = 150 * np.exp(-t * 30) + 50
    phase = 2 * np.pi * np.cumsum(freq) / sr
    kick = np.sin(phase) * np.exp(-t * 15)
    return kick * 0.8


def generate_hihat(sr):
    """Generate a hi-hat sound."""
    duration = 0.05
    n = int(duration * sr)
    noise = np.random.randn(n) * np.exp(-np.arange(n) / sr * 80)
    return noise * 0.15


def generate_snare(sr):
    """Generate a snare sound."""
    duration = 0.1
    n = int(duration * sr)
    t = np.arange(n) / sr
    body = np.sin(2 * np.pi * 200 * t) * np.exp(-t * 30)
    noise = np.random.randn(n) * np.exp(-t * 20)
    return (body * 0.4 + noise * 0.3)


def generate_bass(sr, bpm, note_freq=55.0):
    """Generate a bass note."""
    duration = 60.0 / bpm * 0.5
    t = np.arange(int(duration * sr)) / sr
    env = np.exp(-t * 3)
    bass = np.sin(2 * np.pi * note_freq * t) * env
    bass += 0.3 * np.sin(2 * np.pi * note_freq * 2 * t) * env  # Harmonic
    return bass * 0.4


def generate_pad(sr, duration, freq=220.0, detune=2.0):
    """Generate a pad sound."""
    t = np.arange(int(duration * sr)) / sr
    pad = (np.sin(2 * np.pi * freq * t) +
           0.5 * np.sin(2 * np.pi * (freq + detune) * t) +
           0.3 * np.sin(2 * np.pi * freq * 2 * t))
    # Slow attack/release
    env = np.minimum(t / 1.0, 1.0) * np.minimum((duration - t) / 1.0, 1.0)
    return pad * env * 0.15


def generate_edm_track(bpm, duration, sr, genre="house"):
    """Generate a full EDM track with proper arrangement."""
    n_samples = int(duration * sr)
    y = np.zeros(n_samples)
    beat_samples = int(60.0 / bpm * sr)
    bar_samples = beat_samples * 4

    kick = generate_kick(sr, bpm)
    hihat = generate_hihat(sr)
    snare = generate_snare(sr)

    # EDM arrangement (in bars):
    # Intro (8 bars) → Buildup (8 bars) → Drop (16 bars) →
    # Breakdown (8 bars) → Buildup (8 bars) → Drop (16 bars) → Outro (8 bars)
    total_bars = int(duration / (60.0 / bpm * 4))

    sections = []
    if total_bars >= 64:
        sections = [
            ("intro", 0, 8),
            ("buildup", 8, 16),
            ("drop", 16, 32),
            ("breakdown", 32, 40),
            ("buildup2", 40, 48),
            ("drop2", 48, 64),
            ("outro", 64, min(72, total_bars)),
        ]
    elif total_bars >= 32:
        sections = [
            ("intro", 0, 4),
            ("buildup", 4, 8),
            ("drop", 8, 16),
            ("breakdown", 16, 20),
            ("buildup2", 20, 24),
            ("drop2", 24, 32),
        ]
    else:
        sections = [
            ("intro", 0, 2),
            ("drop", 2, total_bars - 2),
            ("outro", total_bars - 2, total_bars),
        ]

    for section_name, start_bar, end_bar in sections:
        start_sample = start_bar * bar_samples
        end_sample = min(end_bar * bar_samples, n_samples)

        is_drop = "drop" in section_name
        is_buildup = "buildup" in section_name
        is_intro = section_name in ("intro", "outro")

        for bar in range(start_bar, end_bar):
            bar_start = bar * bar_samples
            if bar_start >= n_samples:
                break

            for beat in range(4):
                beat_start = bar_start + beat * beat_samples
                if beat_start >= n_samples:
                    break

                # Kick on every beat (house) or selective (DnB)
                if genre == "house" or genre == "trance":
                    if not is_intro or (bar - start_bar) > 1:
                        _mix(y, kick, beat_start)
                elif genre == "dnb":
                    if beat in (0, 2) and (is_drop or is_buildup):
                        _mix(y, kick, beat_start)

                # Hi-hat on off-beats
                if beat % 2 == 1 and (is_drop or is_buildup):
                    _mix(y, hihat, beat_start)
                # Extra hihats for drop
                if is_drop and beat_samples > 100:
                    _mix(y, hihat * 0.5, beat_start + beat_samples // 2)

                # Snare on beats 2 and 4
                if beat in (1, 3) and (is_drop or is_buildup):
                    if genre == "dnb":
                        _mix(y, snare, beat_start)
                    elif beat == 2:
                        _mix(y, snare * 0.7, beat_start)

                # Bass on downbeats during drops
                if beat == 0 and is_drop:
                    bass_freq = 55 if genre != "dnb" else 44
                    bass = generate_bass(sr, bpm, bass_freq)
                    _mix(y, bass, beat_start)

        # Pad for breakdowns and intros
        if section_name in ("breakdown", "intro"):
            pad_duration = (end_bar - start_bar) * 60.0 / bpm * 4
            pad = generate_pad(sr, pad_duration, freq=220 if genre != "trance" else 330)
            _mix(y, pad, start_sample)

        # Buildup: rising noise
        if is_buildup:
            buildup_len = end_sample - start_sample
            t = np.arange(buildup_len) / buildup_len
            noise = np.random.randn(buildup_len) * t * 0.3
            # Add rising pitch sweep
            sweep_freq = np.linspace(200, 2000, buildup_len)
            sweep = np.sin(2 * np.pi * np.cumsum(sweep_freq) / sr) * t * 0.2
            buildup = noise + sweep
            _mix(y, buildup, start_sample)

    # Normalize
    peak = np.max(np.abs(y))
    if peak > 0:
        y = y / peak * 0.9

    return y


def _mix(dest, src, offset):
    """Mix source into destination at offset."""
    end = min(offset + len(src), len(dest))
    if offset < 0 or offset >= len(dest):
        return
    n = end - offset
    dest[offset:end] += src[:n]


def main():
    sr = 44100
    output_dir = Path(__file__).parent.parent / "samples"
    output_dir.mkdir(exist_ok=True)

    tracks = [
        ("house_128bpm", 128.0, 120.0, "house"),
        ("techno_135bpm", 135.0, 90.0, "house"),
        ("dnb_174bpm", 174.0, 90.0, "dnb"),
        ("trance_140bpm", 140.0, 120.0, "trance"),
    ]

    for name, bpm, duration, genre in tracks:
        print(f"Generating {name} ({bpm} BPM, {duration}s, {genre})...")
        y = generate_edm_track(bpm, duration, sr, genre)
        path = output_dir / f"{name}.wav"
        sf.write(str(path), y, sr)
        print(f"  Saved: {path} ({path.stat().st_size / 1024 / 1024:.1f}MB)")

    print(f"\nDone! {len(tracks)} tracks in {output_dir}")


if __name__ == "__main__":
    main()
