"""Tests for NASManager — vj-content folder management on NAS.

All SSH commands are mocked; no actual NAS connection needed.
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

from src.nas import NASManager, DEFAULT_BASE_PATH, DEFAULT_RESOLUME_MOUNT


@pytest.fixture
def nas():
    """NASManager with default settings."""
    return NASManager()


@pytest.fixture
def nas_custom():
    """NASManager with custom settings."""
    return NASManager(
        nas_host="10.0.0.1",
        nas_port=22,
        nas_user="testuser",
        ssh_key=Path("/tmp/test_key"),
        base_path="/data/vj",
        resolume_mount="/Volumes/vj",
    )


# ------------------------------------------------------------------
# Path helpers
# ------------------------------------------------------------------

class TestPathHelpers:
    def test_track_dir(self, nas):
        assert nas._track_dir("My Track (Extended Mix)") == (
            "/volume1/vj-content/My Track (Extended Mix)"
        )

    def test_shows_dir(self, nas):
        assert nas._shows_dir() == "/volume1/vj-content/shows"

    def test_rsv_dir(self, nas):
        assert nas._rsv_dir() == "/volume1/vj-content/.rsv"

    def test_get_track_video_path_resolume(self, nas):
        path = nas.get_track_video_path("Nan Slapper (Original Mix)")
        assert path == "/Volumes/vj-content/Nan Slapper (Original Mix)/Nan Slapper (Original Mix).mov"

    def test_get_track_video_path_nas(self, nas):
        path = nas.get_track_video_path("Nan Slapper (Original Mix)", as_resolume_mount="")
        assert path == (
            "/volume1/vj-content/Nan Slapper (Original Mix)/"
            "Nan Slapper (Original Mix).mov"
        )

    def test_get_nas_video_path(self, nas):
        path = nas.get_nas_video_path("Tell Me (Extended Mix)")
        assert path == (
            "/volume1/vj-content/Tell Me (Extended Mix)/Tell Me (Extended Mix).mov"
        )

    def test_get_track_video_path_mp4(self, nas):
        path = nas.get_track_video_path("My Track", extension=".mp4")
        assert path == "/Volumes/vj-content/My Track/My Track.mp4"

    def test_custom_base_and_mount(self, nas_custom):
        path = nas_custom.get_track_video_path("Song")
        assert path == "/Volumes/vj/Song/Song.mov"
        nas_path = nas_custom.get_nas_video_path("Song")
        assert nas_path == "/data/vj/Song/Song.mov"


# ------------------------------------------------------------------
# SSH transport
# ------------------------------------------------------------------

class TestSSHTransport:
    @patch("subprocess.run")
    def test_ssh_cmd_builds_correct_args(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"OK", stderr=b""
        )
        nas._ssh_cmd('echo "hello"')
        args = mock_run.call_args[0][0]
        assert args[0] == "ssh"
        assert "-p" in args
        assert "7844" in args
        assert "willcurran@192.168.1.221" in args
        assert args[-1] == 'echo "hello"'

    @patch("subprocess.run")
    def test_push_file_creates_dir_first(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"", stderr=b""
        )
        with patch("builtins.open", mock_open(read_data=b"data")):
            nas._push_file(Path("/tmp/video.mov"), "/volume1/vj-content/Track/video.mov")

        # First call: mkdir, second call: cat >
        assert mock_run.call_count == 2
        mkdir_cmd = mock_run.call_args_list[0][0][0][-1]
        assert "mkdir -p" in mkdir_cmd

    @patch("subprocess.run")
    def test_push_file_raises_on_failure(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"Permission denied"
        )
        with patch("builtins.open", mock_open(read_data=b"data")):
            with pytest.raises(RuntimeError, match="Failed to push to NAS"):
                nas._push_file(Path("/tmp/video.mov"), "/volume1/vj-content/Track/video.mov")


# ------------------------------------------------------------------
# Folder creation
# ------------------------------------------------------------------

class TestFolderCreation:
    @patch("subprocess.run")
    def test_create_track_folder(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"", stderr=b""
        )
        result = nas.create_track_folder("Nan Slapper (Original Mix)")
        assert result == "/volume1/vj-content/Nan Slapper (Original Mix)"
        cmd = mock_run.call_args[0][0][-1]
        assert "keyframes" in cmd
        assert "stems" in cmd

    @patch("subprocess.run")
    def test_create_track_folder_raises_on_failure(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"disk full"
        )
        with pytest.raises(RuntimeError):
            nas.create_track_folder("Track")

    @patch("subprocess.run")
    def test_ensure_structure(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"", stderr=b""
        )
        nas.ensure_structure()
        cmd = mock_run.call_args[0][0][-1]
        assert "shows" in cmd
        assert ".rsv" in cmd


# ------------------------------------------------------------------
# Push operations
# ------------------------------------------------------------------

class TestPushOperations:
    @patch.object(NASManager, "_push_file")
    @patch.object(NASManager, "create_track_folder")
    def test_push_video(self, mock_create, mock_push, nas):
        result = nas.push_video(Path("/tmp/out.mov"), "My Track", codec="mov")
        assert result == "/volume1/vj-content/My Track/My Track.mov"
        mock_create.assert_called_once_with("My Track")
        mock_push.assert_called_once()

    @patch.object(NASManager, "_push_file")
    @patch.object(NASManager, "create_track_folder")
    def test_push_preview(self, mock_create, mock_push, nas):
        result = nas.push_preview(Path("/tmp/preview.mp4"), "My Track")
        assert result == "/volume1/vj-content/My Track/My Track.mp4"

    @patch.object(NASManager, "_push_file")
    @patch.object(NASManager, "create_track_folder")
    def test_push_metadata(self, mock_create, mock_push, nas):
        meta = {"title": "My Track", "bpm": 128}
        result = nas.push_metadata(meta, "My Track")
        assert result == "/volume1/vj-content/My Track/metadata.json"
        mock_push.assert_called_once()
        # Verify the temp file was cleaned up (call already completed)

    @patch.object(NASManager, "_push_file")
    def test_push_keyframe(self, mock_push, nas):
        result = nas.push_keyframe(
            Path("/tmp/kf.png"), "My Track", "segment_000_intro.png"
        )
        assert result == (
            "/volume1/vj-content/My Track/keyframes/segment_000_intro.png"
        )

    @patch.object(NASManager, "_push_file")
    def test_push_stem(self, mock_push, nas):
        result = nas.push_stem(Path("/tmp/drums.wav"), "My Track", "drums")
        assert result == "/volume1/vj-content/My Track/stems/drums.wav"

    @patch.object(NASManager, "_push_file")
    @patch.object(NASManager, "ensure_structure")
    def test_push_show(self, mock_ensure, mock_push, nas):
        result = nas.push_show(Path("/tmp/show.avc"), "Will See")
        assert result == "/volume1/vj-content/shows/Will See.avc"
        # Should push to both shows/ and top-level
        assert mock_push.call_count == 2


# ------------------------------------------------------------------
# Query operations
# ------------------------------------------------------------------

class TestQueryOperations:
    @patch("subprocess.run")
    def test_list_tracks(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=b"Nan Slapper (Original Mix)\nTell Me (Extended Mix)\nshows\n.rsv\nWill See.avc\n",
            stderr=b"",
        )
        tracks = nas.list_tracks()
        assert tracks == ["Nan Slapper (Original Mix)", "Tell Me (Extended Mix)"]

    @patch("subprocess.run")
    def test_list_tracks_empty(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"shows\n.rsv\n", stderr=b""
        )
        tracks = nas.list_tracks()
        assert tracks == []

    @patch("subprocess.run")
    def test_track_exists_true(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"", stderr=b""
        )
        assert nas.track_exists("My Track") is True

    @patch("subprocess.run")
    def test_track_exists_false(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b""
        )
        assert nas.track_exists("Missing Track") is False

    @patch("subprocess.run")
    def test_track_has_video_true(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"EXISTS", stderr=b""
        )
        assert nas.track_has_video("My Track") is True

    @patch("subprocess.run")
    def test_track_has_video_false(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b""
        )
        assert nas.track_has_video("My Track") is False

    @patch("subprocess.run")
    def test_get_track_info_not_found(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b""
        )
        info = nas.get_track_info("Missing")
        assert info["exists"] is False

    @patch("subprocess.run")
    def test_get_track_info_found(self, mock_run, nas):
        def ssh_side_effect(args, **kwargs):
            cmd = args[-1]
            if "test -d" in cmd:
                return subprocess.CompletedProcess(args, 0, b"", b"")
            elif "find" in cmd:
                return subprocess.CompletedProcess(
                    args, 0,
                    b"-rw-r--r-- 1 user group 1048576 Jan 1 12:00 /volume1/vj-content/Track/Track.mov\n",
                    b"",
                )
            elif "cat" in cmd and "metadata.json" in cmd:
                meta = json.dumps({"title": "Track", "bpm": 128}).encode()
                return subprocess.CompletedProcess(args, 0, meta, b"")
            return subprocess.CompletedProcess(args, 0, b"", b"")

        mock_run.side_effect = ssh_side_effect
        info = nas.get_track_info("Track")
        assert info["exists"] is True
        assert info["total_size"] == 1048576
        assert info["metadata"]["bpm"] == 128


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

class TestRegistry:
    @patch("subprocess.run")
    def test_read_registry_empty(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b""
        )
        reg = nas._read_registry()
        assert reg == {"tracks": {}, "version": 1}

    @patch("subprocess.run")
    def test_read_registry_valid(self, mock_run, nas):
        data = json.dumps({"tracks": {"Song": {"bpm": 130}}, "version": 1}).encode()
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=data, stderr=b""
        )
        reg = nas._read_registry()
        assert "Song" in reg["tracks"]
        assert reg["tracks"]["Song"]["bpm"] == 130

    @patch.object(NASManager, "_write_registry")
    @patch.object(NASManager, "_read_registry")
    def test_register_track(self, mock_read, mock_write, nas):
        mock_read.return_value = {"tracks": {}, "version": 1}
        nas.register_track("New Song", {"artist": "DJ", "bpm": 128})
        mock_write.assert_called_once()
        registry = mock_write.call_args[0][0]
        assert "New Song" in registry["tracks"]
        assert registry["tracks"]["New Song"]["artist"] == "DJ"


# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------

class TestCleanup:
    @patch("subprocess.run")
    def test_clean_test_files_dry_run(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=b"will_see_v1\nwill_see_v2\ntest_output\nNan Slapper (Original Mix)\nshows\n",
            stderr=b"",
        )
        removed = nas.clean_test_files(dry_run=True)
        assert sorted(removed) == ["test_output", "will_see_v1", "will_see_v2"]
        # Only one SSH call (ls), no rm calls in dry_run
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_clean_test_files_real(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=b"will_see_v3\ndev_test\nReal Track\n",
            stderr=b"",
        )
        removed = nas.clean_test_files(dry_run=False)
        assert sorted(removed) == ["dev_test", "will_see_v3"]
        # 1 ls + 2 rm calls
        assert mock_run.call_count == 3

    @patch("subprocess.run")
    def test_clean_no_test_files(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=b"Nan Slapper (Original Mix)\nshows\n.rsv\n",
            stderr=b"",
        )
        removed = nas.clean_test_files()
        assert removed == []


# ------------------------------------------------------------------
# Pull metadata
# ------------------------------------------------------------------

class TestPullMetadata:
    @patch("subprocess.run")
    def test_pull_metadata_exists(self, mock_run, nas):
        meta = {"title": "Track", "bpm": 130, "artist": "DJ"}
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps(meta).encode(),
            stderr=b"",
        )
        result = nas.pull_metadata("Track")
        assert result["bpm"] == 130

    @patch("subprocess.run")
    def test_pull_metadata_missing(self, mock_run, nas):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b""
        )
        result = nas.pull_metadata("Missing")
        assert result == {}
