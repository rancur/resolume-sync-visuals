"""Tests for Resolume Arena composition (.avc) export."""
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.resolume.composition import create_composition


def _make_test_composition():
    """Create test composition data."""
    tmpdir = tempfile.mkdtemp()
    for name in ["drop_001.mp4", "buildup_001.mp4", "breakdown_001.mp4", "intro_001.mp4"]:
        (Path(tmpdir) / name).write_bytes(b"\x00" * 1000)

    return {
        "track": "Test Track",
        "bpm": 128.0,
        "duration": 240.0,
        "time_signature": 4,
        "clips": [],
        "loops": [
            {"file": str(Path(tmpdir) / "drop_001.mp4"), "label": "drop", "beats": 32, "duration": 15.0, "bpm": 128.0},
            {"file": str(Path(tmpdir) / "buildup_001.mp4"), "label": "buildup", "beats": 16, "duration": 7.5, "bpm": 128.0},
            {"file": str(Path(tmpdir) / "breakdown_001.mp4"), "label": "breakdown", "beats": 16, "duration": 7.5, "bpm": 128.0},
            {"file": str(Path(tmpdir) / "intro_001.mp4"), "label": "intro", "beats": 16, "duration": 7.5, "bpm": 128.0},
        ],
        "resolume_mapping": [],
    }


def test_create_composition():
    """Test basic composition creation."""
    comp = _make_test_composition()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.avc"
        result = create_composition(comp, output)

        assert result.exists()
        assert result.stat().st_size > 100

        # Should be valid XML
        tree = ET.parse(str(result))
        root = tree.getroot()
        assert root is not None


def test_composition_has_tempo():
    """Test that composition includes BPM."""
    comp = _make_test_composition()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.avc"
        create_composition(comp, output)

        content = output.read_text()
        assert "128" in content


def test_composition_has_layers():
    """Test that composition has clip entries."""
    comp = _make_test_composition()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.avc"
        create_composition(comp, output)

        content = output.read_text()
        # Should reference clip files
        assert "drop" in content.lower() or "mp4" in content.lower()
