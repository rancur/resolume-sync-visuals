"""Tests for the production show builder and Resolume API client."""
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.resolume.show import (
    auto_rebuild_show,
    build_production_show,
    add_track_to_show,
    list_show_tracks,
    rebuild_show_from_output_dir,
    push_show_to_resolume,
    create_denon_show_composition,
    build_denon_show_from_output_dir,
)
from src.resolume.api import ResolumeAPI


# ------------------------------------------------------------------
# Test data helpers
# ------------------------------------------------------------------


def _sample_tracks(n: int = 3) -> list[dict]:
    """Create n sample track dicts."""
    tracks = [
        {
            "title": "Nan Slapper (Original Mix)",
            "artist": "Artist A",
            "video_path": "/Volumes/vj-content/Show/Songs/Nan Slapper/Nan Slapper (Original Mix).mov",
            "bpm": 128.0,
            "duration": 360.0,
        },
        {
            "title": "Tell Me (Extended Mix)",
            "artist": "Artist B",
            "video_path": "/Volumes/vj-content/Show/Songs/Tell Me/Tell Me (Extended Mix).mov",
            "bpm": 126.0,
            "duration": 420.0,
        },
        {
            "title": "Jump Up (Original Mix)",
            "artist": "Artist C",
            "video_path": "/Volumes/vj-content/Show/Songs/Jump Up/Jump Up (Original Mix).mov",
            "bpm": 130.0,
            "duration": 300.0,
        },
    ]
    return tracks[:n]


# ------------------------------------------------------------------
# build_production_show tests
# ------------------------------------------------------------------


class TestBuildProductionShow:
    """Tests for build_production_show()."""

    def test_basic_build(self):
        """Build a show with 3 tracks and verify output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "My Show.avc"
            result = build_production_show(_sample_tracks(), avc_path)

            assert result["show_name"] == "My Show"
            assert result["track_count"] == 3
            assert len(result["tracks"]) == 3
            assert avc_path.exists()

            # Check manifest was created
            manifest_path = Path(result["manifest_path"])
            assert manifest_path.exists()

    def test_avc_xml_structure(self):
        """Verify the .avc XML has correct structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "My Show.avc"
            build_production_show(_sample_tracks(), avc_path)

            xml_content = avc_path.read_text()
            root = ET.fromstring(xml_content.split("\n", 1)[1] if xml_content.startswith("<?xml") else xml_content)

            # Root should be Composition
            assert root.tag == "Composition"
            assert root.get("name") == "My Show"
            assert root.get("numColumns") == "3"
            assert root.get("numLayers") == "1"

            # Should have versionInfo
            ver = root.find("versionInfo")
            assert ver is not None
            assert ver.get("name") == "Resolume Arena"

            # Should have CompositionInfo
            info = root.find("CompositionInfo")
            assert info is not None
            assert info.get("width") == "1920"

            # Should have a Layer with 3 Clips
            layer = root.find("Layer")
            assert layer is not None
            clips = layer.findall("Clip")
            assert len(clips) == 3

            # Each clip should have transport and source
            for i, clip in enumerate(clips):
                assert clip.get("clipIndex") == str(i)

                # Check source
                source = clip.find("PrimarySource")
                assert source is not None
                video_source = source.find("VideoSource")
                assert video_source is not None
                file_ref = video_source.find("VideoFormatReaderSource")
                assert file_ref is not None
                assert file_ref.get("fileName") != ""

                # Check transport
                transport = clip.find("Transport")
                assert transport is not None

            # Should have Columns
            columns = root.findall("Column")
            assert len(columns) == 3

            # Should have Deck
            deck = root.find("Deck")
            assert deck is not None
            assert deck.get("numColumns") == "3"

    def test_clip_titles_match(self):
        """Verify clip names match track titles exactly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "test.avc"
            tracks = _sample_tracks()
            build_production_show(tracks, avc_path)

            tree = ET.parse(str(avc_path))
            root = tree.getroot()

            layer = root.find("Layer")
            clips = layer.findall("Clip")

            for clip, track in zip(clips, tracks):
                params = clip.find("Params")
                name_param = params.find("Param[@name='Name']")
                assert name_param.get("value") == track["title"]

    def test_manifest_content(self):
        """Verify manifest JSON content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "My Show.avc"
            result = build_production_show(_sample_tracks(), avc_path)

            manifest = json.loads(Path(result["manifest_path"]).read_text())
            assert manifest["show_name"] == "My Show"
            assert manifest["track_count"] == 3
            assert len(manifest["tracks"]) == 3
            assert manifest["tracks"][0]["title"] == "Nan Slapper (Original Mix)"
            assert "generated_at" in manifest

    def test_empty_tracks_raises(self):
        """Empty track list should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "test.avc"
            with pytest.raises(ValueError, match="No tracks provided"):
                build_production_show([], avc_path)

    def test_tracks_missing_title_skipped(self):
        """Tracks without title should be filtered out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "test.avc"
            tracks = [
                {"title": "", "video_path": "/some/path.mov"},
                {"title": "Good Track", "video_path": "/good/path.mov"},
            ]
            result = build_production_show(tracks, avc_path)
            assert result["track_count"] == 1
            assert result["tracks"] == ["Good Track"]

    def test_tracks_missing_video_skipped(self):
        """Tracks without video_path should be filtered out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "test.avc"
            tracks = [
                {"title": "No Video", "video_path": ""},
                {"title": "Good Track", "video_path": "/good/path.mov"},
            ]
            result = build_production_show(tracks, avc_path)
            assert result["track_count"] == 1

    def test_all_invalid_tracks_raises(self):
        """If all tracks are filtered out, should raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "test.avc"
            tracks = [{"title": "", "video_path": ""}]
            with pytest.raises(ValueError, match="No valid tracks"):
                build_production_show(tracks, avc_path)

    def test_custom_show_name(self):
        """Custom show name is used in composition and manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "House Set.avc"
            result = build_production_show(
                _sample_tracks(1), avc_path, show_name="House Set"
            )
            assert result["show_name"] == "House Set"

            tree = ET.parse(str(avc_path))
            assert tree.getroot().get("name") == "House Set"

    def test_local_vj_path_fallback(self):
        """Should accept local_vj_path as fallback for video_path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "test.avc"
            tracks = [{
                "title": "Test Track",
                "local_vj_path": "/Volumes/vj-content/Test/Test.mov",
            }]
            result = build_production_show(tracks, avc_path)
            assert result["track_count"] == 1


# ------------------------------------------------------------------
# add_track_to_show tests
# ------------------------------------------------------------------


class TestAddTrackToShow:
    """Tests for add_track_to_show()."""

    def test_add_to_existing(self):
        """Add a track to an existing show."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "My Show.avc"
            result1 = build_production_show(_sample_tracks(2), avc_path)

            new_track = {
                "title": "New Track (Original Mix)",
                "artist": "New Artist",
                "video_path": "/Volumes/vj-content/New Track/New Track.mov",
                "bpm": 125.0,
                "duration": 350.0,
            }
            manifest_path = Path(result1["manifest_path"])
            result2 = add_track_to_show(new_track, manifest_path)

            assert result2["track_count"] == 3
            assert "New Track (Original Mix)" in result2["tracks"]

    def test_add_duplicate_updates(self):
        """Adding a track with same title should update, not duplicate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "My Show.avc"
            result1 = build_production_show(_sample_tracks(2), avc_path)

            updated_track = {
                "title": "Nan Slapper (Original Mix)",
                "artist": "Updated Artist",
                "video_path": "/new/path.mov",
                "bpm": 130.0,
            }
            manifest_path = Path(result1["manifest_path"])
            result2 = add_track_to_show(updated_track, manifest_path)

            # Should still be 2 tracks (replaced, not added)
            assert result2["track_count"] == 2

    def test_manifest_not_found(self):
        """Should raise if manifest doesn't exist."""
        with pytest.raises(FileNotFoundError):
            add_track_to_show(
                {"title": "X", "video_path": "/x.mov"},
                Path("/nonexistent/manifest.json"),
            )


# ------------------------------------------------------------------
# list_show_tracks tests
# ------------------------------------------------------------------


class TestListShowTracks:
    """Tests for list_show_tracks()."""

    def test_list_tracks(self):
        """List tracks from a manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "My Show.avc"
            result = build_production_show(_sample_tracks(), avc_path)

            tracks = list_show_tracks(Path(result["manifest_path"]))
            assert len(tracks) == 3
            assert tracks[0]["title"] == "Nan Slapper (Original Mix)"

    def test_list_not_found(self):
        """Should raise if manifest not found."""
        with pytest.raises(FileNotFoundError):
            list_show_tracks(Path("/nonexistent/manifest.json"))


# ------------------------------------------------------------------
# rebuild_show_from_output_dir tests
# ------------------------------------------------------------------


class TestRebuildShowFromOutputDir:
    """Tests for rebuild_show_from_output_dir()."""

    def test_rebuild_from_track_metadata(self):
        """Rebuild from directories with track_metadata.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            # Create fake track directories with metadata
            for i, t in enumerate(_sample_tracks()):
                track_dir = base / f"track_{i}"
                track_dir.mkdir()
                meta = {
                    "title": t["title"],
                    "artist": t["artist"],
                    "local_vj_path": t["video_path"],
                    "bpm": t["bpm"],
                    "duration": t["duration"],
                }
                (track_dir / "track_metadata.json").write_text(json.dumps(meta))

            avc_path = base / "My Show.avc"
            result = rebuild_show_from_output_dir(base, avc_path)

            assert result["track_count"] == 3
            assert avc_path.exists()

    def test_rebuild_fallback_metadata_json(self):
        """Should fall back to metadata.json if track_metadata.json missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            track_dir = base / "track_0"
            track_dir.mkdir()
            (track_dir / "metadata.json").write_text(json.dumps({
                "title": "Fallback Track",
                "local_vj_path": "/some/path.mov",
            }))

            avc_path = base / "test.avc"
            result = rebuild_show_from_output_dir(base, avc_path)
            assert result["track_count"] == 1

    def test_rebuild_empty_dir_raises(self):
        """Should raise if no tracks found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "test.avc"
            with pytest.raises(ValueError, match="No tracks found"):
                rebuild_show_from_output_dir(Path(tmpdir), avc_path)


# ------------------------------------------------------------------
# push_show_to_resolume tests
# ------------------------------------------------------------------


class TestPushShowToResolume:
    """Tests for push_show_to_resolume()."""

    def test_push_manifest_not_found(self):
        """Should raise if manifest not found."""
        with pytest.raises(FileNotFoundError):
            push_show_to_resolume(Path("/nonexistent/manifest.json"))

    def test_push_empty_manifest_raises(self):
        """Should raise if manifest has no tracks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "empty.manifest.json"
            manifest_path.write_text(json.dumps({
                "show_name": "Empty",
                "tracks": [],
            }))
            with pytest.raises(ValueError, match="No tracks"):
                push_show_to_resolume(manifest_path)

    def test_push_success(self):
        """Test successful push to Resolume API."""
        mock_api = MagicMock()
        mock_api.is_connected.return_value = True
        mock_api.build_denon_show.return_value = 3
        mock_api.__enter__ = MagicMock(return_value=mock_api)
        mock_api.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "My Show.avc"
            build_result = build_production_show(_sample_tracks(), avc_path)
            manifest_path = Path(build_result["manifest_path"])

            with patch("src.resolume.api.ResolumeAPI", return_value=mock_api):
                result = push_show_to_resolume(manifest_path)
            assert result["loaded"] == 3
            assert result["total"] == 3

            mock_api.build_denon_show.assert_called_once()

    def test_push_not_connected(self):
        """Should raise ConnectionError if Resolume not reachable."""
        mock_api = MagicMock()
        mock_api.is_connected.return_value = False
        mock_api.__enter__ = MagicMock(return_value=mock_api)
        mock_api.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "My Show.avc"
            build_result = build_production_show(_sample_tracks(), avc_path)
            manifest_path = Path(build_result["manifest_path"])

            with patch("src.resolume.api.ResolumeAPI", return_value=mock_api):
                with pytest.raises(ConnectionError):
                    push_show_to_resolume(manifest_path)


# ------------------------------------------------------------------
# ResolumeAPI tests
# ------------------------------------------------------------------


class TestResolumeAPI:
    """Tests for the ResolumeAPI client."""

    def test_init(self):
        """Test API client initialization."""
        api = ResolumeAPI(host="10.0.0.1", port=9090)
        assert api.base_url == "http://10.0.0.1:9090/api/v1"
        api.close()

    def test_default_init(self):
        """Test default host/port."""
        api = ResolumeAPI()
        assert api.base_url == "http://127.0.0.1:8080/api/v1"
        api.close()

    @patch("httpx.Client.get")
    def test_is_connected_success(self, mock_get):
        """Test successful connection check."""
        mock_get.return_value = MagicMock(status_code=200)
        api = ResolumeAPI()
        assert api.is_connected() is True
        api.close()

    @patch("httpx.Client.get")
    def test_is_connected_failure(self, mock_get):
        """Test failed connection check."""
        import httpx
        mock_get.side_effect = httpx.ConnectError("refused")
        api = ResolumeAPI()
        assert api.is_connected() is False
        api.close()

    @patch("httpx.Client.post")
    def test_load_clip(self, mock_post):
        """Test loading a video file into a clip."""
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()

        api = ResolumeAPI()
        api.load_clip(1, 1, "/Volumes/vj-content/Track/Track.mov")

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/composition/layers/1/clips/1/open" in call_args[0][0]
        assert call_args[1]["content"] == "file:///Volumes/vj-content/Track/Track.mov"
        api.close()

    @patch("httpx.Client.put")
    def test_set_transport_type(self, mock_put):
        """Test setting clip transport type."""
        mock_put.return_value = MagicMock(status_code=200)
        mock_put.return_value.raise_for_status = MagicMock()

        api = ResolumeAPI()
        api.set_clip_transport_type(1, 1, "Denon")

        call_args = mock_put.call_args
        assert call_args[1]["json"] == {"transporttype": {"value": "Denon"}}
        api.close()

    @patch("httpx.Client.put")
    def test_set_clip_target(self, mock_put):
        """Test setting clip target."""
        mock_put.return_value = MagicMock(status_code=200)
        mock_put.return_value.raise_for_status = MagicMock()

        api = ResolumeAPI()
        api.set_clip_target(1, 1, "Denon Player Determined")

        call_args = mock_put.call_args
        assert call_args[1]["json"] == {"target": {"value": "Denon Player Determined"}}
        api.close()

    @patch("httpx.Client.put")
    def test_set_clip_name(self, mock_put):
        """Test setting clip name."""
        mock_put.return_value = MagicMock(status_code=200)
        mock_put.return_value.raise_for_status = MagicMock()

        api = ResolumeAPI()
        api.set_clip_name(1, 1, "Nan Slapper (Original Mix)")

        call_args = mock_put.call_args
        assert call_args[1]["json"] == {"name": {"value": "Nan Slapper (Original Mix)"}}
        api.close()

    @patch("httpx.Client.post")
    def test_build_denon_show(self, mock_post):
        """Test build_denon_show loads clips and sets transport."""
        mock_response = MagicMock(status_code=200)
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        # Also need to mock PUT for transport/target/name
        with patch("httpx.Client.put") as mock_put:
            mock_put.return_value = mock_response

            api = ResolumeAPI()
            tracks = _sample_tracks(2)
            loaded = api.build_denon_show(tracks, delay_between=0)

            assert loaded == 2
            # Should have called POST (load_clip) for each track
            assert mock_post.call_count == 2
            # Should have called PUT for transport, target, and name for each
            assert mock_put.call_count == 6  # 3 PUTs per track * 2 tracks
            api.close()


# ------------------------------------------------------------------
# Legacy function tests
# ------------------------------------------------------------------


class TestLegacyFunctions:
    """Ensure legacy functions still work."""

    def test_create_denon_show_composition(self):
        """Legacy create_denon_show_composition still works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            avc_path = Path(tmpdir) / "legacy.avc"
            tracks = [
                {"title": "Track 1", "local_vj_path": "/path/1.mov"},
                {"title": "Track 2", "local_vj_path": "/path/2.mov"},
            ]
            result = create_denon_show_composition(tracks, avc_path)
            assert result.exists()

            content = result.read_text()
            assert "Track 1" in content
            assert "Track 2" in content
            assert 'transport="Denon"' in content

    def test_build_denon_show_from_output_dir(self):
        """Legacy build_denon_show_from_output_dir still works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            # Create a track dir with metadata
            track_dir = base / "track_1"
            track_dir.mkdir()
            (track_dir / "track_metadata.json").write_text(json.dumps({
                "title": "Legacy Track",
                "local_vj_path": "/path/legacy.mov",
            }))

            avc_path = base / "legacy.avc"
            result = build_denon_show_from_output_dir(base, avc_path)
            assert result.exists()


# ------------------------------------------------------------------
# auto_rebuild_show tests
# ------------------------------------------------------------------


class TestAutoRebuildShow:
    """Tests for auto_rebuild_show()."""

    def test_rebuilds_from_nas_tracks(self):
        """Scan NAS, find tracks with videos, build and push .avc."""
        mock_nas = MagicMock()
        mock_nas.list_tracks.return_value = [
            "Track A (Original Mix)",
            "Track B (Extended Mix)",
        ]
        mock_nas.track_has_video.return_value = True
        mock_nas.pull_metadata.side_effect = [
            {"artist": "Artist A", "bpm": 128.0, "duration": 300.0},
            {"artist": "Artist B", "bpm": 126.0, "duration": 420.0},
        ]
        mock_nas.get_track_video_path.side_effect = [
            "/Volumes/vj-content/Track A (Original Mix)/Track A (Original Mix).mov",
            "/Volumes/vj-content/Track B (Extended Mix)/Track B (Extended Mix).mov",
        ]

        avc_path = auto_rebuild_show(mock_nas)

        assert avc_path.exists()
        assert avc_path.name == "My Show.avc"
        mock_nas.push_show.assert_called_once()
        # Verify the .avc was passed to push_show
        push_args = mock_nas.push_show.call_args
        assert push_args[0][1] == "My Show"

    def test_skips_tracks_without_video(self):
        """Tracks without video files should be skipped."""
        mock_nas = MagicMock()
        mock_nas.list_tracks.return_value = ["Has Video", "No Video"]
        mock_nas.track_has_video.side_effect = [True, False]
        mock_nas.pull_metadata.return_value = {"artist": "A", "bpm": 128.0}
        mock_nas.get_track_video_path.return_value = "/Volumes/vj-content/Has Video/Has Video.mov"

        avc_path = auto_rebuild_show(mock_nas)

        assert avc_path.exists()
        # Only one track should be in the show
        content = avc_path.read_text()
        assert "Has Video" in content
        assert "No Video" not in content

    def test_no_tracks_raises(self):
        """Should raise if NAS has no tracks."""
        mock_nas = MagicMock()
        mock_nas.list_tracks.return_value = []

        with pytest.raises(ValueError, match="No tracks found"):
            auto_rebuild_show(mock_nas)

    def test_no_tracks_with_video_raises(self):
        """Should raise if no tracks have video files."""
        mock_nas = MagicMock()
        mock_nas.list_tracks.return_value = ["Track Without Video"]
        mock_nas.track_has_video.return_value = False

        with pytest.raises(ValueError, match="No tracks with video"):
            auto_rebuild_show(mock_nas)

    def test_custom_show_name(self):
        """Custom show name is used."""
        mock_nas = MagicMock()
        mock_nas.list_tracks.return_value = ["Track X"]
        mock_nas.track_has_video.return_value = True
        mock_nas.pull_metadata.return_value = {}
        mock_nas.get_track_video_path.return_value = "/Volumes/vj-content/Track X/Track X.mov"

        avc_path = auto_rebuild_show(mock_nas, show_name="House Set")

        assert avc_path.name == "House Set.avc"
        mock_nas.push_show.assert_called_once_with(avc_path, "House Set")
