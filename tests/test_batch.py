"""Tests for OpenAI Batch API support."""
import json
import tempfile
from pathlib import Path

import pytest

from src.generator.batch import prepare_batch, parse_custom_id
from src.generator.engine import GenerationConfig


def test_parse_custom_id():
    """Test custom ID parsing."""
    result = parse_custom_id("track_0_phrase_2_kf_1")
    assert result["track_idx"] == 0
    assert result["phrase_idx"] == 2
    assert result["kf_idx"] == 1


def test_parse_custom_id_formats():
    """Test various custom ID formats."""
    # The function should handle the format it generates
    result = parse_custom_id("track_5_phrase_10_kf_3")
    assert result["track_idx"] == 5
    assert result["phrase_idx"] == 10
    assert result["kf_idx"] == 3


def test_prepare_batch_creates_jsonl():
    """Test batch preparation creates valid JSONL."""
    analysis = {
        "title": "Test Track",
        "bpm": 128.0,
        "duration": 120.0,
        "file_path": "/test.wav",
        "phrases": [
            {"label": "intro", "energy": 0.3, "start": 0, "end": 15, "beats": 32, "spectral_centroid": 2000},
            {"label": "drop", "energy": 0.9, "start": 15, "end": 30, "beats": 32, "spectral_centroid": 3000},
        ],
    }

    config = GenerationConfig(
        style_name="abstract",
        style_config={
            "prompts": {"base": "abstract art", "intro": "calm intro", "drop": "explosive drop"},
            "colors": {"primary": "#FF00FF", "secondary": "#00FFFF"},
            "effects": {},
        },
        backend="openai",
        quality="standard",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir)
        result = prepare_batch([analysis], [config], output_dir)

        assert result.exists()
        assert result.suffix == ".jsonl"

        # Verify JSONL content
        lines = result.read_text().strip().split("\n")
        assert len(lines) > 0

        for line in lines:
            entry = json.loads(line)
            assert "custom_id" in entry
            assert "method" in entry
            assert "url" in entry
            assert "body" in entry
            assert entry["method"] == "POST"
            assert "prompt" in entry["body"]
