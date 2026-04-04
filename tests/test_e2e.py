"""
End-to-end test: analyze synthetic audio → generate visuals → compose.
Uses OpenAI DALL-E for image generation.
"""
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

# Must run with: op run --env-file=.env -- python -m pytest tests/test_e2e.py -v


def make_test_track(bpm=128.0, duration=30.0, sr=22050):
    """Create a test track with energy variation."""
    n = int(duration * sr)
    y = np.zeros(n)
    beat_samples = int(60.0 / bpm * sr)
    click_len = int(0.005 * sr)

    for i in range(0, n, beat_samples):
        beat_num = i // beat_samples
        amp = 0.9 if beat_num % 4 == 0 else 0.5
        end = min(i + click_len, n)
        y[i:end] = amp * np.sin(2 * np.pi * 800 * np.arange(end - i) / sr)

    # Energy curve: low → buildup → drop → breakdown → drop
    sections = [
        (0.0, 0.2, 0.2),    # intro - low
        (0.2, 0.35, 0.5),   # buildup - medium rising
        (0.35, 0.55, 0.9),  # drop - high
        (0.55, 0.7, 0.3),   # breakdown - low
        (0.7, 0.9, 0.95),   # drop 2 - high
        (0.9, 1.0, 0.15),   # outro - low
    ]

    for start_frac, end_frac, energy in sections:
        s = int(start_frac * n)
        e = int(end_frac * n)
        t = np.arange(e - s) / sr
        y[s:e] += energy * 0.3 * (
            np.sin(2 * np.pi * 100 * t) +
            0.5 * np.sin(2 * np.pi * 200 * t) +
            0.3 * np.random.randn(e - s) * energy
        )

    y = np.clip(y, -1.0, 1.0)
    path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    sf.write(path, y, sr)
    return path


def test_full_pipeline():
    """Test complete pipeline: analyze → generate → compose."""
    from src.analyzer.audio import analyze_track
    from src.generator.engine import GenerationConfig, generate_visuals
    from src.composer.timeline import compose_timeline

    # Check API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        import pytest
        pytest.skip("OPENAI_API_KEY not set")

    # Create test audio
    audio_path = make_test_track(bpm=128.0, duration=30.0)
    print(f"\nTest audio: {audio_path}")

    # Analyze
    analysis = analyze_track(audio_path)
    print(f"BPM: {analysis.bpm:.1f}, Phrases: {len(analysis.phrases)}")
    print(f"Structure: {' → '.join(p.label for p in analysis.phrases)}")

    assert len(analysis.phrases) >= 2

    # Only generate for first 2 phrases (save API cost)
    analysis_dict = analysis.to_dict()
    analysis_dict["phrases"] = analysis_dict["phrases"][:2]

    with tempfile.TemporaryDirectory() as tmpdir:
        config = GenerationConfig(
            width=1920,
            height=1080,
            fps=30,
            style_name="abstract",
            style_config={
                "prompts": {
                    "base": "abstract flowing geometric shapes, deep space, prismatic light, 8k",
                    "intro": "dark void, single geometric shape emerging, minimal starfield",
                    "drop": "explosive particle burst, vibrant colors, maximum energy",
                    "buildup": "converging shapes, building light intensity",
                    "breakdown": "gentle floating particles, calm gradient flow",
                    "outro": "dissolving shapes, fading glow",
                },
                "colors": {"primary": "#7B2FBE", "secondary": "#00D4FF"},
                "effects": {"beat_flash_intensity": 0.7, "motion_blur": 0.5},
            },
            backend="openai",
            loop_duration_beats=4,
            quality="standard",  # Save cost
            output_dir=os.path.join(tmpdir, "raw"),
            cache_dir=os.path.join(tmpdir, "cache"),
        )

        def progress(current, total, msg):
            print(f"  [{current}/{total}] {msg}")

        clips = generate_visuals(analysis_dict, config, progress_callback=progress)
        print(f"\nGenerated {len(clips)} clips")

        assert len(clips) > 0

        # Check clips exist and are valid videos
        for clip in clips:
            clip_path = Path(clip["path"])
            assert clip_path.exists(), f"Clip not found: {clip_path}"
            assert clip_path.stat().st_size > 1000, f"Clip too small: {clip_path}"
            print(f"  {clip_path.name}: {clip_path.stat().st_size / 1024:.0f}KB")

        # Compose
        out_dir = os.path.join(tmpdir, "final")
        composition = compose_timeline(analysis_dict, clips, out_dir)

        assert "clips" in composition
        assert "loops" in composition

        meta_path = Path(out_dir) / "metadata.json"
        assert meta_path.exists()

        meta = json.loads(meta_path.read_text())
        print(f"\nComposition: {len(meta['clips'])} clips, {len(meta['loops'])} loops")
        print(f"BPM: {meta['bpm']}")

    print("\n✓ Full pipeline test passed!")


if __name__ == "__main__":
    test_full_pipeline()
