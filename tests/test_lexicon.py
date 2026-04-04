"""Tests for Lexicon DJ integration and the Lexicon-to-Resolume pipeline."""
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.lexicon import (
    LexiconClient,
    VideoGenerationConfig,
    lexicon_to_nas_path,
    lexicon_track_to_analysis_overrides,
    sanitize_track_dirname,
    LEXICON_PATH_PREFIX,
    NAS_PATH_PREFIX,
    NAS_VJ_CONTENT_PREFIX,
    LOCAL_VJ_MOUNT,
)
from src.resolume.show import (
    create_denon_show_composition,
    build_denon_show_from_output_dir,
)


# ── Path mapping tests ──────────────────────────────────────────────


class TestPathMapping:
    """Test Lexicon path to NAS path conversion."""

    def test_standard_path(self):
        lexicon = f"{LEXICON_PATH_PREFIX}Artist/Album/track.flac"
        expected = f"{NAS_PATH_PREFIX}Artist/Album/track.flac"
        assert lexicon_to_nas_path(lexicon) == expected

    def test_preserves_non_lexicon_path(self):
        path = "/some/other/path/track.mp3"
        assert lexicon_to_nas_path(path) == path

    def test_nested_artist_path(self):
        lexicon = f"{LEXICON_PATH_PREFIX}Deep House/DJ Snake/Album/01 - Track.flac"
        expected = f"{NAS_PATH_PREFIX}Deep House/DJ Snake/Album/01 - Track.flac"
        assert lexicon_to_nas_path(lexicon) == expected

    def test_unicode_path(self):
        lexicon = f"{LEXICON_PATH_PREFIX}Beyoncé/Album/Créole.flac"
        expected = f"{NAS_PATH_PREFIX}Beyoncé/Album/Créole.flac"
        assert lexicon_to_nas_path(lexicon) == expected

    def test_empty_path(self):
        assert lexicon_to_nas_path("") == ""


# ── Analysis overrides tests ────────────────────────────────────────


class TestAnalysisOverrides:
    """Test Lexicon metadata to analysis overrides."""

    def test_basic_override(self):
        track = {"bpm": 128, "key": "Am", "genre": "House", "energy": 7, "happiness": 5}
        overrides = lexicon_track_to_analysis_overrides(track)
        assert overrides["bpm"] == 128.0
        assert overrides["key"] == "Am"
        assert overrides["genre"] == "House"
        assert overrides["energy"] == 7
        assert overrides["happiness"] == 5

    def test_dnb_bpm_doubling(self):
        track = {"bpm": 87.5, "genre": "Drum & Bass"}
        overrides = lexicon_track_to_analysis_overrides(track)
        assert overrides["bpm"] == 175.0

    def test_no_bpm_doubling_for_non_dnb(self):
        track = {"bpm": 87.5, "genre": "Deep House"}
        overrides = lexicon_track_to_analysis_overrides(track)
        assert overrides["bpm"] == 87.5

    def test_zero_bpm_excluded(self):
        track = {"bpm": 0}
        overrides = lexicon_track_to_analysis_overrides(track)
        assert "bpm" not in overrides

    def test_none_values_excluded(self):
        track = {"bpm": None, "key": None}
        overrides = lexicon_track_to_analysis_overrides(track)
        assert "bpm" not in overrides
        assert "key" not in overrides

    def test_empty_track(self):
        assert lexicon_track_to_analysis_overrides({}) == {}


# ── Sanitize track dirname ──────────────────────────────────────────


class TestSanitizeTrackDirname:
    """Test track title to directory name sanitization."""

    def test_basic(self):
        assert sanitize_track_dirname("Tell Me (Extended Mix)") == "tell_me_extended_mix"

    def test_special_chars(self):
        assert sanitize_track_dirname("Track! @#$% Name") == "track_name"

    def test_spaces_to_underscores(self):
        assert sanitize_track_dirname("  Multiple   Spaces  ") == "multiple_spaces"

    def test_unicode(self):
        result = sanitize_track_dirname("Café Crème")
        assert "caf" in result


# ── VideoGenerationConfig tests ─────────────────────────────────────


class TestVideoGenerationConfig:
    """Test VideoGenerationConfig defaults."""

    def test_defaults(self):
        cfg = VideoGenerationConfig()
        assert cfg.width == 1920
        assert cfg.height == 1080
        assert cfg.fps == 30
        assert cfg.encode_dxv is True
        assert cfg.skip_existing is True

    def test_custom(self):
        cfg = VideoGenerationConfig(width=3840, height=2160, quality="draft", encode_dxv=False)
        assert cfg.width == 3840
        assert cfg.quality == "draft"
        assert cfg.encode_dxv is False


# ── LexiconClient tests (mocked HTTP) ──────────────────────────────


class TestLexiconClient:
    """Test LexiconClient with mocked HTTP responses."""

    def _mock_response(self, data, status_code=200):
        resp = MagicMock()
        resp.json.return_value = data
        resp.status_code = status_code
        resp.raise_for_status = MagicMock()
        return resp

    def test_test_connection_success(self):
        client = LexiconClient()
        mock_data = {"data": {"total": 42, "tracks": [{"id": 1}]}}

        with patch.object(client, '_get', return_value=mock_data):
            result = client.test_connection()
            assert result["connected"] is True
            assert result["total_tracks"] == 42

    def test_test_connection_failure(self):
        client = LexiconClient()

        with patch.object(client, '_get', side_effect=Exception("Connection refused")):
            result = client.test_connection()
            assert result["connected"] is False
            assert "Connection refused" in result["error"]

    def test_get_track_count(self):
        client = LexiconClient()
        mock_data = {"data": {"total": 100, "tracks": [{"id": 1}]}}

        with patch.object(client, '_get', return_value=mock_data):
            assert client.get_track_count() == 100

    def test_search_tracks(self):
        client = LexiconClient()
        mock_tracks = [
            {"id": 1, "title": "Nan Slapper", "artist": "DJ Test"},
            {"id": 2, "title": "Tell Me", "artist": "Another DJ"},
            {"id": 3, "title": "Nothing Matches", "artist": "Nobody"},
        ]

        with patch.object(client, 'get_tracks', return_value=mock_tracks):
            results = client.search_tracks("nan slapper")
            assert len(results) == 1
            assert results[0]["title"] == "Nan Slapper"

    def test_search_tracks_by_artist(self):
        client = LexiconClient()
        mock_tracks = [
            {"id": 1, "title": "Track 1", "artist": "DJ Snake"},
            {"id": 2, "title": "Track 2", "artist": "Someone Else"},
        ]

        with patch.object(client, 'get_tracks', return_value=mock_tracks):
            results = client.search_tracks("snake")
            assert len(results) == 1
            assert results[0]["artist"] == "DJ Snake"

    def test_get_all_tracks_pagination(self):
        client = LexiconClient()

        batch1 = [{"id": i} for i in range(100)]
        batch2 = [{"id": i} for i in range(100, 150)]

        call_count = 0

        def mock_get_tracks(limit=50, offset=0, fields=None):
            nonlocal call_count
            call_count += 1
            if offset == 0:
                return batch1
            elif offset == 100:
                return batch2
            return []

        with patch.object(client, 'get_tracks', side_effect=mock_get_tracks):
            tracks = client.get_all_tracks()
            assert len(tracks) == 150
            assert call_count == 2  # Two batches


# ── Denon show composition tests ────────────────────────────────────


class TestDenonShowComposition:
    """Test Resolume .avc generation with Denon transport mode."""

    def _sample_tracks(self):
        return [
            {
                "title": "Nan Slapper (Original Mix)",
                "artist": "Test Artist 1",
                "bpm": 128.0,
                "local_vj_path": "/Volumes/vj-content/nan_slapper/Nan Slapper (Original Mix).mov",
            },
            {
                "title": "Tell Me (Extended Mix)",
                "artist": "Test Artist 2",
                "bpm": 125.0,
                "local_vj_path": "/Volumes/vj-content/tell_me/Tell Me (Extended Mix).mov",
            },
        ]

    def test_creates_valid_xml(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test_show.avc"
            result = create_denon_show_composition(tracks, output)

            assert result.exists()
            assert result.stat().st_size > 100

            # Parse XML
            tree = ET.parse(str(result))
            root = tree.getroot()
            assert root.tag == "Arena"

    def test_denon_transport_mode(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_denon_show_composition(tracks, output)

            tree = ET.parse(str(output))
            clips = tree.findall(".//Clip")

            for clip in clips:
                assert clip.get("transport") == "Denon"

    def test_denon_track_name_matches_title(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_denon_show_composition(tracks, output)

            tree = ET.parse(str(output))
            clips = tree.findall(".//Clip")

            titles = {t["title"] for t in tracks}
            for clip in clips:
                assert clip.get("denonTrackName") in titles
                assert clip.get("name") == clip.get("denonTrackName")

    def test_two_deck_layers(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_denon_show_composition(tracks, output, n_decks=2)

            tree = ET.parse(str(output))
            layers = tree.findall(".//Layer")

            assert len(layers) == 2
            assert layers[0].get("name") == "Deck 1"
            assert layers[1].get("name") == "Deck 2"

    def test_each_layer_has_all_clips(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_denon_show_composition(tracks, output, n_decks=2)

            tree = ET.parse(str(output))
            layers = tree.findall(".//Layer")

            for layer in layers:
                clips = layer.findall("Clip")
                assert len(clips) == len(tracks)

    def test_source_paths_set(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_denon_show_composition(tracks, output)

            tree = ET.parse(str(output))
            sources = tree.findall(".//Source")
            paths = {s.get("path") for s in sources}

            for t in tracks:
                assert t["local_vj_path"] in paths

    def test_video_dimensions(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_denon_show_composition(tracks, output)

            tree = ET.parse(str(output))
            videos = tree.findall(".//Video")

            for v in videos:
                assert v.get("width") == "1920"
                assert v.get("height") == "1080"

    def test_composition_name(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_denon_show_composition(tracks, output, show_name="My Show")

            tree = ET.parse(str(output))
            comp = tree.find(".//Composition")
            assert comp.get("name") == "My Show"

    def test_deck_name(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_denon_show_composition(tracks, output, show_name="Will See")

            tree = ET.parse(str(output))
            deck = tree.find(".//Deck")
            assert deck.get("name") == "Will See"

    def test_empty_tracks_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            with pytest.raises(ValueError, match="No tracks"):
                create_denon_show_composition([], output)

    def test_custom_deck_count(self):
        tracks = self._sample_tracks()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            create_denon_show_composition(tracks, output, n_decks=4)

            tree = ET.parse(str(output))
            layers = tree.findall(".//Layer")
            assert len(layers) == 4

    def test_single_track(self):
        tracks = [self._sample_tracks()[0]]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "test.avc"
            result = create_denon_show_composition(tracks, output)
            assert result.exists()

            tree = ET.parse(str(result))
            clips = tree.findall(".//Clip")
            # 2 decks * 1 track = 2 clips
            assert len(clips) == 2


class TestBuildDenonShowFromOutputDir:
    """Test scanning output directory for track metadata."""

    def test_finds_track_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake track directories with metadata
            for name, title in [("track_a", "Track A"), ("track_b", "Track B")]:
                track_dir = Path(tmpdir) / name
                track_dir.mkdir()
                meta = {
                    "title": title,
                    "artist": "Test",
                    "bpm": 128.0,
                    "local_vj_path": f"/Volumes/vj-content/{name}/{title}.mov",
                }
                (track_dir / "track_metadata.json").write_text(json.dumps(meta))

            output = Path(tmpdir) / "show.avc"
            result = build_denon_show_from_output_dir(tmpdir, output)

            assert result.exists()
            tree = ET.parse(str(result))
            clips = tree.findall(".//Clip")
            # 2 tracks * 2 decks = 4 clips
            assert len(clips) == 4

    def test_skips_dirs_without_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # One valid, one without metadata
            valid_dir = Path(tmpdir) / "valid"
            valid_dir.mkdir()
            meta = {
                "title": "Valid Track",
                "artist": "Test",
                "bpm": 128.0,
                "local_vj_path": "/Volumes/vj-content/valid/Valid Track.mov",
            }
            (valid_dir / "track_metadata.json").write_text(json.dumps(meta))

            empty_dir = Path(tmpdir) / "empty"
            empty_dir.mkdir()

            output = Path(tmpdir) / "show.avc"
            result = build_denon_show_from_output_dir(tmpdir, output)
            assert result.exists()

            tree = ET.parse(str(result))
            clips = tree.findall(".//Clip")
            # 1 track * 2 decks = 2 clips
            assert len(clips) == 2

    def test_empty_dir_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "show.avc"
            with pytest.raises(ValueError, match="No tracks found"):
                build_denon_show_from_output_dir(tmpdir, output)
