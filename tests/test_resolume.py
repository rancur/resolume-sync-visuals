"""Tests for the Resolume export module."""
import json
import tempfile
from pathlib import Path

from src.resolume.export import create_resolume_deck, generate_resolume_osc_script


def _make_test_composition():
    """Create a minimal test composition."""
    tmpdir = tempfile.mkdtemp()
    # Create fake video files
    for name in ["loop_drop_000.mp4", "loop_buildup_000.mp4", "loop_breakdown_000.mp4", "loop_intro_000.mp4"]:
        p = Path(tmpdir) / name
        p.write_bytes(b"\x00" * 1000)  # Dummy file

    return {
        "track": "Test Track",
        "bpm": 128.0,
        "duration": 240.0,
        "time_signature": 4,
        "clips": [],
        "loops": [
            {"file": str(Path(tmpdir) / "loop_drop_000.mp4"), "label": "drop", "beats": 32, "bars": 8, "duration": 15.0, "bpm": 128.0},
            {"file": str(Path(tmpdir) / "loop_buildup_000.mp4"), "label": "buildup", "beats": 16, "bars": 4, "duration": 7.5, "bpm": 128.0},
            {"file": str(Path(tmpdir) / "loop_breakdown_000.mp4"), "label": "breakdown", "beats": 16, "bars": 4, "duration": 7.5, "bpm": 128.0},
            {"file": str(Path(tmpdir) / "loop_intro_000.mp4"), "label": "intro", "beats": 16, "bars": 4, "duration": 7.5, "bpm": 128.0},
        ],
        "resolume_mapping": [],
    }


def test_create_resolume_deck():
    """Test Resolume deck creation."""
    comp = _make_test_composition()
    with tempfile.TemporaryDirectory() as outdir:
        deck_dir = create_resolume_deck(comp, outdir)

        assert deck_dir.exists()
        assert (deck_dir / "deck_info.json").exists()

        # Check layer directories exist
        assert (deck_dir / "Layer1_Drops").exists()
        assert (deck_dir / "Layer2_Buildups").exists()
        assert (deck_dir / "Layer3_Breakdowns").exists()
        assert (deck_dir / "Layer4_Ambient").exists()

        # Check clips were copied
        drop_clips = list((deck_dir / "Layer1_Drops").glob("*.mp4"))
        assert len(drop_clips) == 1

        # Check deck_info
        info = json.loads((deck_dir / "deck_info.json").read_text())
        assert info["bpm"] == 128.0
        assert info["total_clips"] == 4


def test_generate_osc_script():
    """Test OSC trigger script generation."""
    comp = _make_test_composition()
    script = generate_resolume_osc_script(comp)

    assert "#!/usr/bin/env python3" in script
    assert "128.0" in script  # BPM
    assert "Test Track" in script
    assert "trigger_clip" in script
    assert "set_master_bpm" in script

    # Verify it's valid Python (syntax check)
    compile(script, "<osc_script>", "exec")


def test_osc_script_to_file():
    """Test writing OSC script to file."""
    comp = _make_test_composition()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "trigger.py"
        generate_resolume_osc_script(comp, path)

        assert path.exists()
        assert path.stat().st_size > 100
        # Check executable
        import stat
        assert path.stat().st_mode & stat.S_IXUSR
