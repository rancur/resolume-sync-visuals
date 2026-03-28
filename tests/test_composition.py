"""Tests for Resolume Arena composition (.avc) export."""
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.resolume.composition import (
    create_composition,
    create_multi_track_composition,
    _organize_clips_by_layer,
    _prettify_xml,
)


def _make_test_composition(tmpdir=None):
    """Create test composition data with dummy clip files."""
    if tmpdir is None:
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


class TestCreateComposition:
    """Test single-track composition generation."""

    def test_creates_valid_xml(self):
        """Output is valid XML."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            result = create_composition(comp, output)

            assert result.exists()
            assert result.stat().st_size > 100

            tree = ET.parse(str(result))
            root = tree.getroot()
            assert root.tag == "Arena"

    def test_has_composition_element(self):
        """XML contains Composition element with track name."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            root = tree.getroot()
            composition = root.find("Composition")
            assert composition is not None
            assert composition.get("name") == "Test Track"

    def test_has_tempo(self):
        """XML contains Tempo element with correct BPM."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            tempo = tree.find(".//Tempo")
            assert tempo is not None
            assert tempo.get("bpm") == "128.0"

    def test_has_deck(self):
        """XML contains a Deck element."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            deck = tree.find(".//Deck")
            assert deck is not None
            assert deck.get("name") == "Test Track"

    def test_has_layers(self):
        """XML contains Layer elements for each configured layer."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            layers = tree.findall(".//Layer")
            assert len(layers) == 4

            layer_names = {l.get("name") for l in layers}
            assert "Drops" in layer_names
            assert "Buildups" in layer_names
            assert "Breakdowns" in layer_names
            assert "Ambient" in layer_names

    def test_has_clips(self):
        """XML contains Clip elements with correct attributes."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            clips = tree.findall(".//Clip")
            assert len(clips) == 4

            # Check clip attributes
            for clip in clips:
                assert clip.get("transport") == "BPMSync"
                assert clip.get("beats") is not None
                assert int(clip.get("beats")) > 0

    def test_clips_have_source_paths(self):
        """Each clip has a Source element with a path."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            sources = tree.findall(".//Source")
            assert len(sources) == 4
            for src in sources:
                assert src.get("path") is not None
                assert len(src.get("path")) > 0

    def test_clips_have_video_dimensions(self):
        """Each clip has Video element with width/height."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            videos = tree.findall(".//Video")
            assert len(videos) == 4
            for v in videos:
                assert int(v.get("width")) > 0
                assert int(v.get("height")) > 0

    def test_relative_paths_with_base(self):
        """Clip paths are made relative when clip_base_path is given."""
        with tempfile.TemporaryDirectory() as tmpdir:
            comp = _make_test_composition(tmpdir)
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output, clip_base_path=Path(tmpdir))

            tree = ET.parse(str(output))
            sources = tree.findall(".//Source")
            for src in sources:
                path = src.get("path")
                # Should be relative (no leading /)
                assert not path.startswith("/"), f"Path should be relative: {path}"

    def test_output_parent_dirs_created(self):
        """Output parent directories are created if needed."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "nested" / "dir" / "test.avc"
            result = create_composition(comp, output)
            assert result.exists()

    def test_returns_output_path(self):
        """Function returns the output path."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            result = create_composition(comp, output)
            assert result == output

    def test_empty_loops_uses_clips(self):
        """Falls back to clips when no loops available."""
        comp = _make_test_composition()
        comp["loops"] = []
        comp["clips"] = [
            {"file": "/fake/clip.mp4", "label": "drop", "beats": 16},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            clips = tree.findall(".//Clip")
            assert len(clips) == 1

    def test_layer_blend_modes(self):
        """Layers have blend mode attributes."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            layers = tree.findall(".//Layer")
            for layer in layers:
                assert layer.get("blendMode") is not None

    def test_layer_opacity(self):
        """Layers have opacity attributes."""
        comp = _make_test_composition()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_composition(comp, output)

            tree = ET.parse(str(output))
            layers = tree.findall(".//Layer")
            for layer in layers:
                opacity = float(layer.get("opacity"))
                assert 0.0 <= opacity <= 1.0


class TestMultiTrackComposition:
    """Test multi-track composition generation."""

    def test_creates_valid_xml(self):
        """Multi-track output is valid XML."""
        tracks = [_make_test_composition(), _make_test_composition()]
        tracks[0]["track"] = "Track A"
        tracks[1]["track"] = "Track B"
        tracks[1]["bpm"] = 140.0

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "set.avc"
            result = create_multi_track_composition(tracks, output)

            assert result.exists()
            tree = ET.parse(str(result))
            assert tree.getroot().tag == "Arena"

    def test_has_multiple_decks(self):
        """Each track becomes a separate Deck."""
        tracks = [_make_test_composition(), _make_test_composition()]
        tracks[0]["track"] = "Track A"
        tracks[1]["track"] = "Track B"

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "set.avc"
            create_multi_track_composition(tracks, output)

            tree = ET.parse(str(output))
            decks = tree.findall(".//Deck")
            assert len(decks) == 2

            deck_names = {d.get("name") for d in decks}
            assert "Track A" in deck_names
            assert "Track B" in deck_names

    def test_master_tempo_from_first_track(self):
        """Master tempo uses first track's BPM."""
        tracks = [_make_test_composition(), _make_test_composition()]
        tracks[0]["bpm"] = 130.0
        tracks[1]["bpm"] = 145.0

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "set.avc"
            create_multi_track_composition(tracks, output)

            tree = ET.parse(str(output))
            tempo = tree.find(".//Tempo")
            assert tempo.get("bpm") == "130.0"

    def test_empty_tracks_raises(self):
        """Empty track list raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "set.avc"
            with pytest.raises(ValueError, match="No tracks provided"):
                create_multi_track_composition([], output)

    def test_each_deck_has_layers(self):
        """Each deck contains the expected layers."""
        tracks = [_make_test_composition()]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "set.avc"
            create_multi_track_composition(tracks, output)

            tree = ET.parse(str(output))
            deck = tree.find(".//Deck")
            layers = deck.findall("Layer")
            assert len(layers) == 4

    def test_returns_output_path(self):
        """Function returns the output path."""
        tracks = [_make_test_composition()]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "set.avc"
            result = create_multi_track_composition(tracks, output)
            assert result == output


class TestOrganizeClipsByLayer:
    """Test clip-to-layer organization."""

    def test_drop_goes_to_layer_1(self):
        """Drop clips go to layer 1."""
        data = {"loops": [{"label": "drop", "file": "a.mp4"}]}
        layers = _organize_clips_by_layer(data)
        assert len(layers[1]) == 1
        assert layers[1][0]["label"] == "drop"

    def test_buildup_goes_to_layer_2(self):
        """Buildup clips go to layer 2."""
        data = {"loops": [{"label": "buildup", "file": "a.mp4"}]}
        layers = _organize_clips_by_layer(data)
        assert len(layers[2]) == 1

    def test_breakdown_goes_to_layer_3(self):
        """Breakdown clips go to layer 3."""
        data = {"loops": [{"label": "breakdown", "file": "a.mp4"}]}
        layers = _organize_clips_by_layer(data)
        assert len(layers[3]) == 1

    def test_intro_outro_go_to_layer_4(self):
        """Intro and outro clips go to layer 4 (Ambient)."""
        data = {"loops": [
            {"label": "intro", "file": "a.mp4"},
            {"label": "outro", "file": "b.mp4"},
        ]}
        layers = _organize_clips_by_layer(data)
        assert len(layers[4]) == 2

    def test_unknown_label_defaults_to_layer_4(self):
        """Unknown labels default to layer 4."""
        data = {"loops": [{"label": "mystery", "file": "a.mp4"}]}
        layers = _organize_clips_by_layer(data)
        assert len(layers[4]) == 1

    def test_falls_back_to_clips(self):
        """Uses 'clips' key when 'loops' is empty."""
        data = {"loops": [], "clips": [{"label": "drop", "file": "a.mp4"}]}
        layers = _organize_clips_by_layer(data)
        assert len(layers[1]) == 1


class TestPrettifyXml:
    """Test XML pretty-printing."""

    def test_produces_xml_declaration(self):
        """Output starts with XML declaration."""
        elem = ET.Element("Root")
        result = _prettify_xml(elem)
        assert result.startswith("<?xml")

    def test_produces_indented_output(self):
        """Output has indentation."""
        root = ET.Element("Root")
        ET.SubElement(root, "Child", name="test")
        result = _prettify_xml(root)
        assert "  " in result  # Has indentation

    def test_no_extra_blank_lines(self):
        """No consecutive blank lines in output."""
        root = ET.Element("Root")
        ET.SubElement(root, "A")
        ET.SubElement(root, "B")
        result = _prettify_xml(root)
        assert "\n\n" not in result
