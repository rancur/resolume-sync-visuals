"""Tests for genre detection and style auto-selection."""
import tempfile

import numpy as np
import pytest
import soundfile as sf

from src.analyzer.genre import detect_genre_and_style, _classify_genre, GENRE_STYLE_MAP


def _make_audio(bpm: float = 128.0, duration: float = 15.0, sr: int = 22050,
                bass_heavy: bool = False, bright: bool = False) -> str:
    """Generate a synthetic test audio file with controllable characteristics."""
    n_samples = int(duration * sr)
    y = np.zeros(n_samples)

    beat_interval = int(60.0 / bpm * sr)
    click_len = int(0.01 * sr)

    # Clicks at beat positions (kick pattern)
    for i in range(0, n_samples, beat_interval):
        end = min(i + click_len, n_samples)
        y[i:end] = 0.6 * np.sin(2 * np.pi * 1000 * np.arange(end - i) / sr)

    # Bass content
    t = np.arange(n_samples) / sr
    if bass_heavy:
        y += 0.4 * np.sin(2 * np.pi * 60 * t) + 0.2 * np.sin(2 * np.pi * 120 * t)
    else:
        y += 0.05 * np.sin(2 * np.pi * 80 * t)

    # Brightness
    if bright:
        y += 0.15 * np.sin(2 * np.pi * 6000 * t) + 0.1 * np.sin(2 * np.pi * 8000 * t)

    # Normalize
    peak = np.max(np.abs(y))
    if peak > 0:
        y = y / peak * 0.9

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, y, sr)
    return tmp.name


def test_detect_genre_and_style_returns_tuple():
    """detect_genre_and_style returns a (genre, style) tuple."""
    audio_path = _make_audio(bpm=128.0, duration=10.0)
    result = detect_genre_and_style(audio_path)
    assert isinstance(result, tuple)
    assert len(result) == 2
    genre, style = result
    assert isinstance(genre, str)
    assert isinstance(style, str)
    assert len(genre) > 0
    assert len(style) > 0


def test_detected_style_is_valid():
    """The recommended style should be one of the available style presets."""
    from pathlib import Path
    style_dir = Path(__file__).parent.parent / "config" / "styles"
    available = {f.stem for f in style_dir.glob("*.yaml")}

    audio_path = _make_audio(bpm=130.0, duration=10.0)
    _, style = detect_genre_and_style(audio_path)
    assert style in available, f"Style '{style}' not in available styles: {available}"


def test_genre_in_known_set():
    """Detected genre should be one of the known genre keys."""
    known_genres = set(GENRE_STYLE_MAP.keys())
    audio_path = _make_audio(bpm=128.0, duration=10.0)
    genre, _ = detect_genre_and_style(audio_path)
    assert genre in known_genres, f"Genre '{genre}' not in known genres: {known_genres}"


def test_classify_genre_house_bpm():
    """House-range BPM with moderate features should favor house."""
    genre = _classify_genre(
        bpm=128.0,
        mean_centroid=2000.0,
        onset_density=4.0,
        bass_ratio=0.3,
        mean_flatness=0.1,
        rms_std=0.03,
        onset_std=0.5,
    )
    assert genre in ("house", "techno"), f"Expected house/techno for 128 BPM, got {genre}"


def test_classify_genre_dnb_bpm():
    """DnB-range BPM with heavy bass and fast transients should favor DnB."""
    genre = _classify_genre(
        bpm=172.0,
        mean_centroid=3500.0,
        onset_density=7.0,
        bass_ratio=0.5,
        mean_flatness=0.15,
        rms_std=0.04,
        onset_std=1.0,
    )
    assert genre == "dnb", f"Expected dnb for 172 BPM + heavy bass, got {genre}"


def test_classify_genre_trance_bpm():
    """Trance-range BPM with tonal content should favor trance."""
    genre = _classify_genre(
        bpm=140.0,
        mean_centroid=2200.0,
        onset_density=3.5,
        bass_ratio=0.2,
        mean_flatness=0.03,
        rms_std=0.06,
        onset_std=0.8,
    )
    assert genre == "trance", f"Expected trance for 140 BPM + tonal, got {genre}"


def test_classify_genre_ambient():
    """Slow BPM with low centroid and sparse onsets should favor ambient."""
    genre = _classify_genre(
        bpm=90.0,
        mean_centroid=1200.0,
        onset_density=1.5,
        bass_ratio=0.1,
        mean_flatness=0.04,
        rms_std=0.01,
        onset_std=0.3,
    )
    assert genre == "ambient", f"Expected ambient for 90 BPM + sparse, got {genre}"


def test_classify_genre_hard():
    """High centroid with dense transients should favor hard."""
    genre = _classify_genre(
        bpm=150.0,
        mean_centroid=4000.0,
        onset_density=8.0,
        bass_ratio=0.3,
        mean_flatness=0.25,
        rms_std=0.05,
        onset_std=1.5,
    )
    assert genre == "hard", f"Expected hard for bright + dense transients, got {genre}"


def test_genre_style_map_completeness():
    """Every genre in the map should point to at least one valid style."""
    from pathlib import Path
    style_dir = Path(__file__).parent.parent / "config" / "styles"
    available = {f.stem for f in style_dir.glob("*.yaml")}

    for genre, styles in GENRE_STYLE_MAP.items():
        assert len(styles) > 0, f"Genre '{genre}' has no style mappings"
        for s in styles:
            assert s in available, f"Style '{s}' for genre '{genre}' not found in {available}"
